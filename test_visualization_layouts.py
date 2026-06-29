import unittest

from visualization.layouts import bounds_for, layout_for_type
from visualization.svg_renderer import render_educational_diagram_svg


def node(node_id, label):
    return {"id": node_id, "label": label}


def edge(start, end):
    return {"from": start, "to": end}


COMPLEX_MIND_MAPS = {
    "Photosynthesis": {
        "nodes": [
            node("root", "Photosynthesis"),
            node("inputs", "Raw materials needed by green plants"),
            node("light", "Sunlight energy trapped by chlorophyll"),
            node("carbon", "Carbon dioxide from air"),
            node("water", "Water absorbed by roots"),
            node("site", "Leaf and chloroplast structure"),
            node("stomata", "Stomata gas exchange"),
            node("products", "Products formed after photosynthesis"),
            node("glucose", "Glucose stored as starch"),
            node("oxygen", "Oxygen released to atmosphere"),
        ],
        "connections": [
            edge("root", "inputs"),
            edge("inputs", "carbon"),
            edge("inputs", "water"),
            edge("root", "light"),
            edge("root", "site"),
            edge("site", "stomata"),
            edge("root", "products"),
            edge("products", "glucose"),
            edge("products", "oxygen"),
        ],
    },
    "The Human Digestive System": {
        "nodes": [
            node("root", "The Human Digestive System"),
            node("mouth", "Mouth begins mechanical and chemical digestion"),
            node("path", "Food passage through alimentary canal"),
            node("oesophagus", "Oesophagus uses peristalsis"),
            node("stomach", "Stomach churns food with acid and enzymes"),
            node("intestines", "Small and large intestines"),
            node("small", "Small intestine absorbs nutrients"),
            node("large", "Large intestine absorbs water"),
            node("organs", "Accessory organs supporting digestion"),
            node("liver", "Liver produces bile"),
            node("pancreas", "Pancreas releases digestive enzymes"),
        ],
        "connections": [
            edge("root", "mouth"),
            edge("root", "path"),
            edge("path", "oesophagus"),
            edge("path", "stomach"),
            edge("path", "intestines"),
            edge("intestines", "small"),
            edge("intestines", "large"),
            edge("root", "organs"),
            edge("organs", "liver"),
            edge("organs", "pancreas"),
        ],
    },
    "The Periodic Table": {
        "nodes": [
            node("root", "The Periodic Table"),
            node("organization", "Organized by atomic number and recurring properties"),
            node("periods", "Periods are horizontal rows"),
            node("groups", "Groups are vertical columns with similar behavior"),
            node("families", "Important element families"),
            node("alkali", "Alkali metals react strongly with water"),
            node("halogens", "Halogens form salts easily"),
            node("noble", "Noble gases are mostly unreactive"),
            node("blocks", "Blocks show electron sub-shell filling"),
            node("metals", "Metals, nonmetals, and metalloids"),
            node("trends", "Periodic trends"),
            node("radius", "Atomic radius changes across periods and groups"),
            node("electronegativity", "Electronegativity increases toward fluorine"),
        ],
        "connections": [
            edge("root", "organization"),
            edge("organization", "periods"),
            edge("organization", "groups"),
            edge("root", "families"),
            edge("families", "alkali"),
            edge("families", "halogens"),
            edge("families", "noble"),
            edge("root", "blocks"),
            edge("root", "metals"),
            edge("root", "trends"),
            edge("trends", "radius"),
            edge("trends", "electronegativity"),
        ],
    },
}


class MindMapLayoutTests(unittest.TestCase):
    def assert_no_node_overlaps(self, nodes):
        for index, left in enumerate(nodes):
            left_box = (
                left["x"] - left["width"] / 2,
                left["y"] - left["height"] / 2,
                left["x"] + left["width"] / 2,
                left["y"] + left["height"] / 2,
            )
            for right in nodes[index + 1:]:
                right_box = (
                    right["x"] - right["width"] / 2,
                    right["y"] - right["height"] / 2,
                    right["x"] + right["width"] / 2,
                    right["y"] + right["height"] / 2,
                )
                separated = (
                    left_box[2] <= right_box[0]
                    or right_box[2] <= left_box[0]
                    or left_box[3] <= right_box[1]
                    or right_box[3] <= left_box[1]
                )
                self.assertTrue(separated, f"{left['label']} overlaps {right['label']}")

    def assert_parents_center_child_subtrees(self, nodes, connections):
        by_id = {item["id"]: item for item in nodes}
        children = {}
        for connection in connections:
            children.setdefault(connection["from"], []).append(connection["to"])

        for parent_id, child_ids in children.items():
            valid_children = [by_id[child_id] for child_id in child_ids if child_id in by_id]
            if not valid_children:
                continue
            expected_center = (
                min(child["subtree_left"] for child in valid_children)
                + max(child["subtree_right"] for child in valid_children)
            ) / 2
            self.assertAlmostEqual(by_id[parent_id]["x"], expected_center, places=5)
            self.assertLess(by_id[parent_id]["y"], min(child["y"] for child in valid_children))

    def test_complex_mind_maps_do_not_overlap_and_center_parents(self):
        for topic, payload in COMPLEX_MIND_MAPS.items():
            with self.subTest(topic=topic):
                laid_out = layout_for_type("mind_map", payload["nodes"], payload["connections"])
                self.assert_no_node_overlaps(laid_out)
                self.assert_parents_center_child_subtrees(laid_out, payload["connections"])

                width, height = bounds_for(laid_out)
                self.assertGreaterEqual(width, 760)
                self.assertGreaterEqual(height, 500)
                self.assert_no_node_overlaps(laid_out)

    def test_mind_map_svg_wraps_long_labels_and_expands_canvas(self):
        payload = {
            "available": True,
            "type": "mind_map",
            "title": "The Periodic Table",
            **COMPLEX_MIND_MAPS["The Periodic Table"],
        }

        svg = render_educational_diagram_svg(payload)

        self.assertIn("<tspan", svg)
        self.assertIn("viewBox=", svg)
        self.assertIn("Atomic radius changes", svg)
        self.assertNotRegex(svg, r'="[^"]*NaN')

    def test_mind_map_layout_positions_disconnected_cycles(self):
        nodes = [
            node("root", "Main Topic"),
            node("branch", "Branch"),
            node("cycle-a", "Disconnected cycle A"),
            node("cycle-b", "Disconnected cycle B"),
        ]
        connections = [
            edge("root", "branch"),
            edge("cycle-a", "cycle-b"),
            edge("cycle-b", "cycle-a"),
        ]

        laid_out = layout_for_type("mind_map", nodes, connections)

        self.assertEqual({item["id"] for item in laid_out}, {"root", "branch", "cycle-a", "cycle-b"})
        self.assertTrue(all("x" in item and "y" in item for item in laid_out))
        self.assert_no_node_overlaps(laid_out)


class EducationalIllustrationRendererTests(unittest.TestCase):
    def assert_educational_svg(self, svg, template):
        self.assertIn("ai-visualization-svg", svg)
        self.assertIn(f"edu-template-{template}", svg)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', svg)
        self.assertIn("@media (prefers-color-scheme: dark)", svg)
        self.assertIn("@media (max-width: 640px)", svg)
        self.assertNotIn("viz-node-shape", svg)
        self.assertNotRegex(svg, r'="[^"]*NaN')

    def test_photosynthesis_renderer_draws_textbook_illustration(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "template": "photosynthesis",
                "type": "scientific_process",
                "title": "Photosynthesis",
                "labels": ["Sunlight", "Water", "Carbon dioxide", "Oxygen", "Glucose", "Leaf"],
            }
        )

        self.assert_educational_svg(svg, "photosynthesis")
        self.assertIn("url(#eduSun)", svg)
        self.assertIn("url(#eduLeaf)", svg)
        self.assertIn("Glucose", svg)

    def test_plant_cell_renderer_draws_organelles(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "template": "plant_cell",
                "type": "anatomy",
                "title": "Plant Cell",
                "labels": ["Cell wall", "Cell membrane", "Nucleus", "Chloroplast", "Vacuole", "Cytoplasm"],
            }
        )

        self.assert_educational_svg(svg, "plant_cell")
        self.assertIn("Cell wall", svg)
        self.assertIn("Chloroplast", svg)
        self.assertIn("Vacuole", svg)

    def test_animal_cell_renderer_draws_organelles(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "template": "animal_cell",
                "type": "anatomy",
                "title": "Animal Cell",
                "labels": ["Cell membrane", "Cytoplasm", "Nucleus", "Mitochondria", "Ribosomes"],
            }
        )

        self.assert_educational_svg(svg, "animal_cell")
        self.assertIn("Mitochondria", svg)
        self.assertIn("Ribosomes", svg)

    def test_water_cycle_renderer_draws_landscape_cycle(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "template": "water_cycle",
                "type": "cycle",
                "title": "Water Cycle",
                "labels": ["Evaporation", "Condensation", "Precipitation", "Collection"],
            }
        )

        self.assert_educational_svg(svg, "water_cycle")
        self.assertIn("Evaporation", svg)
        self.assertIn("Precipitation", svg)
        self.assertIn("url(#eduOcean)", svg)

    def test_timeline_renderer_uses_horizontal_timeline(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "template": "timeline",
                "type": "timeline",
                "title": "French Revolution Timeline",
                "labels": ["Estates-General", "Tennis Court Oath", "Bastille", "Republic", "Napoleon"],
            }
        )

        self.assert_educational_svg(svg, "timeline")
        self.assertIn("Chronological event illustration", svg)
        self.assertIn("Bastille", svg)

    def test_solar_system_renderer_draws_orbits(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "template": "solar_system",
                "type": "orbit",
                "title": "Solar System",
                "labels": ["Sun", "Mercury", "Venus", "Earth", "Mars", "Jupiter"],
            }
        )

        self.assert_educational_svg(svg, "solar_system")
        self.assertIn("Orbit-based planetary illustration", svg)
        self.assertIn("<ellipse", svg)
        self.assertIn("Jupiter", svg)

    def test_food_chain_renderer_draws_organisms(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "template": "food_chain",
                "type": "chain",
                "title": "Food Chain",
                "labels": ["Sun", "Grass", "Grasshopper", "Frog", "Snake", "Hawk"],
            }
        )

        self.assert_educational_svg(svg, "food_chain")
        self.assertIn("Energy transfer between organisms", svg)
        self.assertIn("Grasshopper", svg)

    def test_unknown_visualization_falls_back_to_generic_renderer(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "type": "process",
                "title": "Generic Process",
                "nodes": [node("1", "First"), node("2", "Second")],
                "connections": [edge("1", "2")],
            }
        )

        self.assertIn("viz-node-shape", svg)
        self.assertNotIn("edu-template-", svg)
        self.assertIn("Process Diagram", svg)

    def test_backward_compatible_payload_infers_specialized_renderer(self):
        svg = render_educational_diagram_svg(
            {
                "available": True,
                "type": "scientific_process",
                "title": "Photosynthesis",
                "nodes": [
                    node("1", "Sunlight"),
                    node("2", "Water"),
                    node("3", "Carbon dioxide"),
                    node("4", "Oxygen"),
                ],
                "connections": [edge("1", "4"), edge("2", "4"), edge("3", "4")],
            }
        )

        self.assert_educational_svg(svg, "photosynthesis")
        self.assertIn("Sunlight", svg)


if __name__ == "__main__":
    unittest.main()
