"""Tests for the skills loader system."""

import os
import json


def test_parse_front_matter_valid():
    """Valid YAML front matter is parsed correctly."""
    import skills_loader

    text = """---
name: test_skill
description: A test skill
specialist: writer
trigger_keywords:
  - hello
  - world
---

# Body content here
"""
    metadata, body = skills_loader._parse_front_matter(text)
    assert metadata['name'] == 'test_skill'
    assert metadata['description'] == 'A test skill'
    assert metadata['specialist'] == 'writer'
    assert metadata['trigger_keywords'] == ['hello', 'world']
    assert 'Body content here' in body


def test_parse_front_matter_missing():
    """Text without front matter returns empty metadata."""
    import skills_loader

    text = "Just some plain text without front matter."
    metadata, body = skills_loader._parse_front_matter(text)
    assert metadata == {}
    assert body == text


def test_parse_front_matter_list_values():
    """List values in front matter are parsed as lists."""
    import skills_loader

    text = """---
name: multi
trigger_keywords:
  - one
  - two
  - three
---

Body
"""
    metadata, body = skills_loader._parse_front_matter(text)
    assert isinstance(metadata['trigger_keywords'], list)
    assert len(metadata['trigger_keywords']) == 3


def test_list_skills_returns_expected_fields():
    """list_skills() returns dicts with required fields."""
    import skills_loader
    skills_loader.reload_skills()

    skills = skills_loader.list_skills()
    if skills:  # only check if skills dir exists
        for s in skills:
            assert 'name' in s
            assert 'description' in s
            assert 'specialist' in s
            assert 'is_builtin' in s


def test_get_skill_missing():
    """get_skill() returns None for nonexistent skill."""
    import skills_loader
    skills_loader.reload_skills()

    assert skills_loader.get_skill('nonexistent_skill_xyz') is None


def test_match_skill_irrelevant_message():
    """match_skill() returns None for irrelevant messages."""
    import skills_loader
    skills_loader.reload_skills()

    result = skills_loader.match_skill("hello how are you today")
    assert result is None


def test_builtin_skills_set():
    """BUILTIN_SKILLS contains the 5 starter files."""
    import skills_loader

    assert len(skills_loader.BUILTIN_SKILLS) == 5
    assert 'cover_letter.md' in skills_loader.BUILTIN_SKILLS
    assert 'research.md' in skills_loader.BUILTIN_SKILLS
    assert 'code_review.md' in skills_loader.BUILTIN_SKILLS
    assert 'email_draft.md' in skills_loader.BUILTIN_SKILLS
    assert 'job_analysis.md' in skills_loader.BUILTIN_SKILLS


def test_reload_picks_up_new_files(tmp_path, monkeypatch):
    """Reload detects new skill files added to the directory."""
    import skills_loader

    # Create a temp skills dir with one skill
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "test_skill.md").write_text("""---
name: test_skill
description: A test
specialist: coder
trigger_keywords:
  - testing
---

Test body.
""")

    monkeypatch.setattr(skills_loader, 'SKILLS_DIR', str(skills_dir))
    skills_loader.reload_skills()

    skills = skills_loader.list_skills()
    assert len(skills) == 1
    assert skills[0]['name'] == 'test_skill'

    # Add another skill file
    (skills_dir / "new_skill.md").write_text("""---
name: new_skill
description: Brand new
specialist: analyst
trigger_keywords:
  - analyze
---

New body.
""")

    skills_loader.reload_skills()
    skills = skills_loader.list_skills()
    assert len(skills) == 2
    names = {s['name'] for s in skills}
    assert 'new_skill' in names


def test_keyword_matching(tmp_path, monkeypatch):
    """match_skill() finds skills by keyword presence in message."""
    import skills_loader

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "writer_skill.md").write_text("""---
name: writer_skill
description: Writing help
specialist: writer
trigger_keywords:
  - cover letter
  - application letter
---

Write well.
""")

    monkeypatch.setattr(skills_loader, 'SKILLS_DIR', str(skills_dir))
    skills_loader.reload_skills()

    result = skills_loader.match_skill("please write a cover letter for me")
    assert result is not None
    assert result['name'] == 'writer_skill'


def test_specialist_filtering(tmp_path, monkeypatch):
    """match_skill() filters by specialist when specified."""
    import skills_loader

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "coder_skill.md").write_text("""---
name: coder_skill
description: Code help
specialist: coder
trigger_keywords:
  - code review
---

Review code.
""")

    monkeypatch.setattr(skills_loader, 'SKILLS_DIR', str(skills_dir))
    skills_loader.reload_skills()

    # Should match when specialist matches
    result = skills_loader.match_skill("do a code review", specialist_name="coder")
    assert result is not None
    assert result['name'] == 'coder_skill'

    # Should NOT match when specialist doesn't match
    result = skills_loader.match_skill("do a code review", specialist_name="writer")
    assert result is None


def test_empty_skills_dir(tmp_path, monkeypatch):
    """Empty skills directory returns empty list."""
    import skills_loader

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    monkeypatch.setattr(skills_loader, 'SKILLS_DIR', str(skills_dir))
    skills_loader.reload_skills()

    assert skills_loader.list_skills() == []


def test_missing_skills_dir(tmp_path, monkeypatch):
    """Missing skills directory returns empty list without error."""
    import skills_loader

    monkeypatch.setattr(skills_loader, 'SKILLS_DIR', str(tmp_path / "nonexistent"))
    skills_loader.reload_skills()

    assert skills_loader.list_skills() == []
