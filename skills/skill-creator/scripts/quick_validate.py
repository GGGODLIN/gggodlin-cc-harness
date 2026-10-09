#!/usr/bin/env python3
# Modified from the original work at https://github.com/anthropics/skills/tree/main/skills/skill-creator (Apache-2.0, copyright Anthropic, PBC). See THIRD_PARTY_NOTICES.md.
"""
Quick validation script for skills - minimal version
"""

import sys
import os
import re
import yaml
from pathlib import Path


class UniqueKeyLoader(yaml.SafeLoader):
    pass


MERGE_TAG = "tag:yaml.org,2002:merge"


def _mapping_error(node, key_node, problem):
    return yaml.constructor.ConstructorError(
        "while constructing a mapping",
        node.start_mark,
        problem,
        key_node.start_mark,
    )


def _check_nested_mappings(loader, node, seen_nodes):
    if isinstance(node, yaml.nodes.MappingNode):
        _check_mapping(loader, node, seen_nodes)
    elif isinstance(node, yaml.nodes.SequenceNode):
        for child in node.value:
            _check_nested_mappings(loader, child, seen_nodes)


def _check_mapping(loader, node, seen_nodes):
    if id(node) in seen_nodes:
        return
    seen_nodes.add(id(node))
    explicit_keys = []
    for key_node, value_node in node.value:
        if key_node.tag == MERGE_TAG:
            _check_nested_mappings(loader, value_node, seen_nodes)
            continue
        key = loader.construct_object(key_node, deep=False)
        try:
            hash(key)
        except TypeError as error:
            raise _mapping_error(node, key_node, "unhashable YAML key") from error
        if key in explicit_keys:
            raise _mapping_error(node, key_node, f"duplicate key {key!r}")
        explicit_keys.append(key)
        _check_nested_mappings(loader, value_node, seen_nodes)


def _construct_unique_mapping(loader, node, deep=False):
    _check_mapping(loader, node, set())
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)

NUMERIC_COMPARISON = re.compile(
    r"[<>]=?\s*(?:\d+(?:[.,]\d+)?|\.\d+)(?:\s*[kKmMbB])?(?![\w-])"
)
LOWER_HYPHEN_TOKEN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
CONTEXTUAL_PLACEHOLDER = re.compile(
    rf"(?:/<{LOWER_HYPHEN_TOKEN}>(?=/|$|[\s.,;:)\]])|(?<![A-Za-z0-9_-])/{LOWER_HYPHEN_TOKEN}\s+<{LOWER_HYPHEN_TOKEN}>(?![A-Za-z0-9_-]))"
)


def _is_contextual_placeholder(description, position):
    return any(
        match.start() <= position < match.end()
        for match in CONTEXTUAL_PLACEHOLDER.finditer(description)
    )


def _has_invalid_angle_bracket(description):
    for match in re.finditer(r"[<>]", description):
        if not NUMERIC_COMPARISON.match(description, match.start()) and not _is_contextual_placeholder(description, match.start()):
            return True
    return False


def validate_skill(skill_path):
    """Basic validation of a skill"""
    skill_path = Path(skill_path)

    # Check SKILL.md exists
    skill_md = skill_path / 'SKILL.md'
    if not skill_md.exists():
        return False, "SKILL.md not found"

    # Read and validate frontmatter
    try:
        content = skill_md.read_text(encoding='utf-8')
    except UnicodeError:
        return False, "SKILL.md is not valid UTF-8"
    except OSError:
        return False, "Unable to read SKILL.md"
    if not content.startswith('---'):
        return False, "No YAML frontmatter found"

    # Extract frontmatter
    match = re.match(r'^---\n(.*?)\n---[ \t]*(?:\n|$)', content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format"

    frontmatter_text = match.group(1)

    # Parse YAML frontmatter
    try:
        frontmatter = yaml.load(frontmatter_text, Loader=UniqueKeyLoader)
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary"
    except yaml.constructor.ConstructorError as error:
        if error.problem and (error.problem.startswith("duplicate key") or error.problem == "unhashable YAML key"):
            return False, f"Invalid YAML in frontmatter: {error.problem}"
        return False, f"Invalid YAML in frontmatter: {error}"
    except yaml.YAMLError as error:
        return False, f"Invalid YAML in frontmatter: {error}"

    # Define allowed properties
    ALLOWED_PROPERTIES = {
        'name',
        'description',
        'license',
        'allowed-tools',
        'metadata',
        'upstream',
        'upstream-path',
        'upstream-pinned',
        'upstream-branch',
        'upstream-status',
        'disable-model-invocation',
    }

    # Check for unexpected properties (excluding nested keys under metadata)
    unexpected_keys = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected_keys:
        return False, (
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected_keys))}. "
            f"Allowed properties are: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )

    # Check required fields
    if 'name' not in frontmatter:
        return False, "Missing 'name' in frontmatter"
    if 'description' not in frontmatter:
        return False, "Missing 'description' in frontmatter"

    # Extract name for validation
    name = frontmatter.get('name', '')
    if not isinstance(name, str):
        return False, f"Name must be a string, got {type(name).__name__}"
    name = name.strip()
    if name:
        # Check naming convention (hyphen-case: lowercase with hyphens)
        if not re.match(r'^[a-z0-9-]+$', name):
            return False, f"Name '{name}' should be hyphen-case (lowercase letters, digits, and hyphens only)"
        if name.startswith('-') or name.endswith('-') or '--' in name:
            return False, f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens"
        # Check name length (max 64 characters per spec)
        if len(name) > 64:
            return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters."

    # Extract and validate description
    description = frontmatter.get('description', '')
    if not isinstance(description, str):
        return False, f"Description must be a string, got {type(description).__name__}"
    description = description.strip()
    if description:
        if _has_invalid_angle_bracket(description):
            return False, "Description cannot contain HTML or placeholder angle brackets"
        # Check description length (max 1024 characters per spec)
        if len(description) > 1024:
            return False, f"Description is too long ({len(description)} characters). Maximum is 1024 characters."

    return True, "Skill is valid!"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python quick_validate.py <skill_directory>")
        sys.exit(1)
    
    valid, message = validate_skill(sys.argv[1])
    print(message)
    sys.exit(0 if valid else 1)