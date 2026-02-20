"""Unit tests for Alexandria Cover Designer.

Run: pytest tests/test_unit.py -v
"""

import json
from pathlib import Path

import pytest


# === Configuration Tests ===

class TestConfig:
    """Test configuration loading."""

    def test_config_imports(self):
        """Config module imports without error."""
        from src.config import Config, get_config
        assert Config is not None
        assert get_config is not None

    def test_config_defaults(self):
        """Config has sensible defaults."""
        from src.config import get_config
        config = get_config()
        assert config.image_width == 1024
        assert config.image_height == 1024
        assert config.max_cost_usd > 0
        assert config.cost_per_image_usd > 0

    def test_config_paths(self):
        """Config paths are Path objects."""
        from src.config import get_config
        config = get_config()
        assert isinstance(config.input_covers_dir, Path)
        assert isinstance(config.output_covers_dir, Path)


# === Catalog Tests ===

class TestBookCatalog:
    """Test book catalog data."""

    @pytest.fixture
    def catalog(self):
        catalog_path = Path(__file__).parent.parent / "config" / "book_catalog.json"
        if not catalog_path.exists():
            pytest.skip("book_catalog.json not found")
        with open(catalog_path, encoding='utf-8') as f:
            return json.load(f)

    def test_catalog_is_list(self, catalog):
        assert isinstance(catalog, list)

    def test_catalog_has_entries(self, catalog):
        assert len(catalog) >= 90  # Should have ~99

    def test_catalog_entry_structure(self, catalog):
        entry = catalog[0]
        assert "number" in entry
        assert "title" in entry
        assert "author" in entry
        assert "folder_name" in entry
        assert "file_base" in entry


# === Prompt Template Tests ===

class TestPromptTemplates:
    """Test prompt template configuration."""

    @pytest.fixture
    def templates(self):
        templates_path = Path(__file__).parent.parent / "config" / "prompt_templates.json"
        if not templates_path.exists():
            pytest.skip("prompt_templates.json not found")
        with open(templates_path, encoding='utf-8') as f:
            return json.load(f)

    def test_has_style_anchors(self, templates):
        # Updated schema stores anchors inside style_groups.
        if "style_anchors" in templates:
            assert len(templates["style_anchors"]) > 0
            return

        assert "style_groups" in templates
        groups = templates["style_groups"]
        assert isinstance(groups, dict)
        assert len(groups) > 0
        for group_name, group in groups.items():
            assert "style_anchors" in group, f"Style group {group_name} missing style_anchors"
            assert isinstance(group["style_anchors"], str)
            assert group["style_anchors"].strip()

    def test_has_negative_prompt(self, templates):
        assert "negative_prompt" in templates

    def test_has_5_variants(self, templates):
        assert "variants" in templates
        assert len(templates["variants"]) == 5

    def test_variant_has_template(self, templates):
        for key, variant in templates["variants"].items():
            assert "template" in variant, f"Variant {key} missing template"
            assert "name" in variant, f"Variant {key} missing name"


# === Module Import Tests ===

class TestModuleImports:
    """Verify all source modules can be imported."""

    def test_import_config(self):
        import src.config

    def test_import_cover_analyzer(self):
        import src.cover_analyzer

    def test_import_prompt_generator(self):
        import src.prompt_generator

    def test_import_image_generator(self):
        import src.image_generator

    def test_import_quality_gate(self):
        import src.quality_gate

    def test_import_cover_compositor(self):
        import src.cover_compositor

    def test_import_output_exporter(self):
        import src.output_exporter

    def test_import_pipeline(self):
        import src.pipeline

    def test_import_gdrive_sync(self):
        import src.gdrive_sync
