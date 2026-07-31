import unittest

from visualization.svg_renderer import render_educational_diagram_svg


def node(node_id, label):
    return {"id": node_id, "label": label}


def edge(start, end):
    return {"from": start, "to": end}


class EducationalIllustrationRendererTests(unittest.TestCase):
    def assert_educational_svg(self, svg, template):
        self.assertIn("ai-visualization-svg", svg)
        self.assertIn(f"edu-template-{template}", svg)
        self.assertIn('preserveAspectRatio="xMidYMid meet"', svg)
        self.assertIn("@media (prefers-color-scheme: dark)", svg)
        self.assertIn("@media (max-width: 640px)", svg)
        self.assertIn("edu-legend", svg)
        self.assertIn("edu-label-box", svg)
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
        self.assertIn("Chronological sequence of key events", svg)
        self.assertIn("Bastille", svg)
        self.assertNotIn("Event 1", svg)

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
        self.assertIn("Planet positions along orbital paths", svg)
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
