"""Tests for plugin template generator."""

import json
import os
import sys

import pytest

import plugin_generator


class TestValidateName:
    def test_valid_name(self):
        assert plugin_generator.validate_name("my_plugin") is None

    def test_valid_name_underscores(self):
        assert plugin_generator.validate_name("weather_api_v2") is None

    def test_starts_with_number(self):
        err = plugin_generator.validate_name("2cool")
        assert err is not None
        assert "not a valid" in err

    def test_has_spaces(self):
        err = plugin_generator.validate_name("my plugin")
        assert err is not None

    def test_has_dashes(self):
        err = plugin_generator.validate_name("my-plugin")
        assert err is not None

    def test_reserved_name_example_plugin(self):
        err = plugin_generator.validate_name("example_plugin")
        assert err is not None
        assert "reserved" in err

    def test_reserved_name_pycache(self):
        err = plugin_generator.validate_name("__pycache__")
        assert err is not None

    def test_python_keyword(self):
        err = plugin_generator.validate_name("class")
        assert err is not None
        assert "keyword" in err


class TestGeneratePlugin:
    def test_creates_directory_structure(self, tmp_path):
        plugin_generator.generate_plugin("my_plugin", output_dir=str(tmp_path))
        plugin_dir = tmp_path / "my_plugin"
        assert plugin_dir.is_dir()
        assert (plugin_dir / "__init__.py").is_file()
        assert (plugin_dir / "README.md").is_file()
        assert (plugin_dir / "plugin.json").is_file()

    def test_description_populates(self, tmp_path):
        plugin_generator.generate_plugin(
            "my_plugin", description="Custom desc", output_dir=str(tmp_path),
        )
        init_content = (tmp_path / "my_plugin" / "__init__.py").read_text()
        assert 'PLUGIN_DESCRIPTION = "Custom desc"' in init_content

    def test_default_description(self, tmp_path):
        plugin_generator.generate_plugin("my_plugin", output_dir=str(tmp_path))
        init_content = (tmp_path / "my_plugin" / "__init__.py").read_text()
        assert "PLUGIN_DESCRIPTION" in init_content
        assert '""' not in init_content.split("PLUGIN_DESCRIPTION")[1].split("\n")[0]

    def test_tools_flag_generates_correct_count(self, tmp_path):
        plugin_generator.generate_plugin(
            "my_plugin", tools_count=3, output_dir=str(tmp_path),
        )
        init_content = (tmp_path / "my_plugin" / "__init__.py").read_text()
        assert '"name": "my_plugin_1"' in init_content
        assert '"name": "my_plugin_2"' in init_content
        assert '"name": "my_plugin_3"' in init_content

    def test_single_tool_no_suffix(self, tmp_path):
        plugin_generator.generate_plugin(
            "my_plugin", tools_count=1, output_dir=str(tmp_path),
        )
        init_content = (tmp_path / "my_plugin" / "__init__.py").read_text()
        assert '"name": "my_plugin"' in init_content
        assert '"name": "my_plugin_1"' not in init_content

    def test_wont_overwrite_existing(self, tmp_path):
        plugin_generator.generate_plugin("my_plugin", output_dir=str(tmp_path))
        with pytest.raises(ValueError, match="already exists"):
            plugin_generator.generate_plugin("my_plugin", output_dir=str(tmp_path))

    def test_invalid_name_raises(self, tmp_path):
        with pytest.raises(ValueError, match="not a valid"):
            plugin_generator.generate_plugin("123bad", output_dir=str(tmp_path))

    def test_generated_init_is_importable(self, tmp_path):
        plugin_generator.generate_plugin(
            "loadable_plugin", description="Test", output_dir=str(tmp_path),
        )
        # Add to sys.path and import
        sys.path.insert(0, str(tmp_path))
        try:
            import loadable_plugin
            assert hasattr(loadable_plugin, "PLUGIN_NAME")
            assert hasattr(loadable_plugin, "PLUGIN_DESCRIPTION")
            assert hasattr(loadable_plugin, "PLUGIN_VERSION")
            assert hasattr(loadable_plugin, "TOOLS")
            assert hasattr(loadable_plugin, "get_tools")
            assert hasattr(loadable_plugin, "execute")
            assert isinstance(loadable_plugin.TOOLS, list)
            assert len(loadable_plugin.TOOLS) == 1
            assert callable(loadable_plugin.execute)
            # Execute returns expected tuple
            result, is_error = loadable_plugin.execute(
                "loadable_plugin", {"input": "hello"}, {}, [],
            )
            assert isinstance(result, str)
            assert is_error is False
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("loadable_plugin", None)

    def test_plugin_json_has_required_fields(self, tmp_path):
        plugin_generator.generate_plugin(
            "my_plugin", description="Test desc", output_dir=str(tmp_path),
        )
        meta_path = tmp_path / "my_plugin" / "plugin.json"
        meta = json.loads(meta_path.read_text())
        assert meta["name"] == "my_plugin"
        assert meta["version"] == "0.1.0"
        assert meta["description"] == "Test desc"
        assert "author" in meta
        assert "license" in meta
        assert "dependencies" in meta
        assert isinstance(meta["dependencies"], list)

    def test_readme_has_content(self, tmp_path):
        plugin_generator.generate_plugin(
            "my_plugin", description="Does things", output_dir=str(tmp_path),
        )
        readme = (tmp_path / "my_plugin" / "README.md").read_text()
        assert "My Plugin" in readme
        assert "Does things" in readme
        assert "Installation" in readme
        assert "Tools" in readme

    def test_returns_plugin_dir_path(self, tmp_path):
        result = plugin_generator.generate_plugin("my_plugin", output_dir=str(tmp_path))
        assert result == str(tmp_path / "my_plugin")
