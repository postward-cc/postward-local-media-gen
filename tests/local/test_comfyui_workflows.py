"""Local-only checks for the ComfyUI adapter.

These are deliberately NOT part of ``scripts/check.sh`` and never run in CI.
They validate the committed workflow JSON and the saved-format to API-format
conversion, which is what gives confidence that the video and upscale tools
can still be pushed after an edit — without a GPU, a running ComfyUI or model
weights.

Run them with ``./scripts/check_local.sh``.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / "comfyui-runtime" / "workflows"

_spec = importlib.util.spec_from_file_location(
    "run_workflow", ROOT / "comfyui-runtime" / "run_workflow.py")
run_workflow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_workflow)


def api_graph(path: Path) -> dict:
    """Load a committed workflow and convert it the way a submission does."""
    saved = json.loads(path.read_text())
    return run_workflow.saved_to_api(run_workflow.inline_subgraphs(saved))


class WorkflowGraphTests(unittest.TestCase):
    """Every committed workflow must still produce a submittable graph."""

    def graphs(self):
        for path in sorted(WORKFLOWS.glob("*.json")):
            with self.subTest(workflow=path.name):
                yield path, api_graph(path)

    def test_every_committed_workflow_is_valid_json(self):
        found = sorted(WORKFLOWS.glob("*.json"))
        self.assertTrue(found, "no workflow files found")
        for path in found:
            with self.subTest(workflow=path.name):
                self.assertIsInstance(json.loads(path.read_text()), dict)

    def test_conversion_produces_a_non_empty_graph(self):
        for path, graph in self.graphs():
            self.assertTrue(graph, "conversion produced no nodes")

    def test_every_node_carries_a_class_type(self):
        for path, graph in self.graphs():
            for node_id, node in graph.items():
                with self.subTest(workflow=path.name, node=node_id):
                    self.assertTrue(node.get("class_type"),
                                    "ComfyUI rejects a node without class_type")

    def test_every_link_points_at_a_node_that_exists(self):
        """A dangling reference is the failure a hand-edited workflow causes."""
        for path, graph in self.graphs():
            for node_id, node in graph.items():
                for name, value in node["inputs"].items():
                    if isinstance(value, list) and len(value) == 2 \
                            and isinstance(value[0], str):
                        with self.subTest(workflow=path.name, node=node_id,
                                          input=name):
                            self.assertIn(
                                value[0], graph,
                                f"{name} references missing node {value[0]}")

    def test_notes_never_reach_the_submitted_graph(self):
        for path, graph in self.graphs():
            for node_id, node in graph.items():
                self.assertNotIn("Note", node["class_type"])

    def test_h3_workflows_reach_the_h3_node(self):
        for path in sorted(WORKFLOWS.glob("video_minimax_h3_*.json")):
            with self.subTest(workflow=path.name):
                saved = json.loads(path.read_text())
                h3_id = run_workflow.detect_h3_node_id(saved)
                node = next(n for n in saved["nodes"] if n["id"] == h3_id)
                self.assertIn("widgets_values_named", node)


class PatchContractTests(unittest.TestCase):
    """User-supplied settings must reach the graph, not be silently dropped."""

    def setUp(self):
        self.workflow = json.loads(
            (WORKFLOWS / "video_minimax_h3_t2v.json").read_text())

    def test_every_knob_lands_on_the_h3_node(self):
        patched = run_workflow.patch_workflow(
            self.workflow, megapixels=0.3, duration=2, turbo_steps=8,
            turbo_strength=0.5, seed=431, prompt="A paper owl.")

        node = next(n for n in patched["nodes"]
                    if n["id"] == run_workflow.detect_h3_node_id(self.workflow))
        named = node["widgets_values_named"]
        self.assertEqual(named["prompt"], "A paper owl.")
        self.assertEqual(named["value_1"], 2.0)
        self.assertEqual(named["noise_seed"], 431)
        self.assertEqual(named["value_2"], 8)
        self.assertEqual(named["strength_model_1"], 0.5)
        self.assertTrue(named["value"], "turbo mode was not enabled")

    def test_megapixels_reaches_the_resolution_selector(self):
        patched = run_workflow.patch_workflow(
            self.workflow, megapixels=0.42, duration=None, turbo_steps=None,
            turbo_strength=None, seed=None)

        selector = next(n for n in patched["nodes"]
                        if n["id"] == run_workflow.NODE_RES_SELECTOR_ID)
        self.assertEqual(selector["widgets_values"][1], 0.42)

    def test_patching_does_not_mutate_the_source_workflow(self):
        before = json.dumps(self.workflow, sort_keys=True)

        run_workflow.patch_workflow(
            self.workflow, megapixels=0.9, duration=9, turbo_steps=9,
            turbo_strength=9, seed=9, prompt="changed")

        self.assertEqual(json.dumps(self.workflow, sort_keys=True), before)

    def test_absent_knobs_leave_the_workflow_defaults_alone(self):
        """Turbo mode is the exception: it is always enabled.

        The adapter ships the Turbo LoRA and exposes no opt-out, so a run that
        asks for nothing still runs Turbo. Every other knob keeps the value the
        workflow was saved with.
        """
        patched = run_workflow.patch_workflow(
            self.workflow, megapixels=None, duration=None, turbo_steps=None,
            turbo_strength=None, seed=None)

        h3_id = run_workflow.detect_h3_node_id(self.workflow)
        node = next(n for n in patched["nodes"] if n["id"] == h3_id)
        original = next(n for n in self.workflow["nodes"]
                        if n["id"] == h3_id)["widgets_values_named"]

        self.assertTrue(node["widgets_values_named"]["value"],
                        "turbo mode should be forced on")
        for key, value in original.items():
            if key == "value":
                continue
            with self.subTest(knob=key):
                self.assertEqual(node["widgets_values_named"][key], value)

    def test_patched_workflow_still_converts_to_a_valid_graph(self):
        patched = run_workflow.patch_workflow(
            self.workflow, megapixels=0.3, duration=2, turbo_steps=8,
            turbo_strength=0.5, seed=431, prompt="A paper owl.")

        graph = run_workflow.saved_to_api(
            run_workflow.inline_subgraphs(patched))

        self.assertTrue(graph)
        for node in graph.values():
            self.assertTrue(node["class_type"])


class ConversionTests(unittest.TestCase):
    WORKFLOW = {
        "nodes": [
            {"id": 1, "type": "NoteNode", "widgets_values": ["ignore me"]},
            {"id": 2, "type": "Loader",
             "inputs": [{"name": "unet_name", "widget": "unet_name"}],
             "widgets_values": ["model.safetensors"]},
            {"id": 3, "type": "Sampler",
             "inputs": [{"name": "model", "link": 7},
                        {"name": "steps", "widget": "steps"}],
             "widgets_values": [None, 20]},
        ],
        "links": [[7, 2, 0, 3, 0, "MODEL"]],
    }

    def test_a_link_overrides_the_widget_value_it_replaces(self):
        api = run_workflow.saved_to_api(self.WORKFLOW)

        self.assertEqual(api["3"]["inputs"]["model"], ["2", 0])

    def test_unconnected_inputs_still_come_from_widgets(self):
        api = run_workflow.saved_to_api(self.WORKFLOW)

        self.assertEqual(api["3"]["inputs"]["steps"], 20)
        self.assertEqual(api["2"]["inputs"]["unet_name"], "model.safetensors")

    def test_named_widgets_are_preferred_when_present(self):
        workflow = {"nodes": [{"id": 5, "type": "X",
                               "widgets_values": [1, 2],
                               "widgets_values_named": {"b": 9}}],
                    "links": []}

        api = run_workflow.saved_to_api(workflow)

        self.assertEqual(api["5"]["inputs"], {"b": 9})


if __name__ == "__main__":
    unittest.main()