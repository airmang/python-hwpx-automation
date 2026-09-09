import jsonschema
import pytest

from hwpx_automation.tool_contract import bound_tool_registry, contract_payload


def test_representative_tools_are_exposed_only_through_the_canonical_registry():
    names = set(bound_tool_registry().names)
    assert {"insert_picture", "replace_picture", "render_preview", "repair_hwpx"} <= names
    assert {
        "convert_hwp_to_hwpx",
        "fill_template",
        "analyze_template_structure",
        "open_document_handle",
        "list_open_documents",
        "close_document_handle",
        "copy_table_between_documents",
    }.isdisjoint(names)


def test_canonical_registry_has_normalized_input_and_output_schema_for_all_127_tools():
    registry = bound_tool_registry()
    assert len(registry.tools) == 136
    for item in registry.tools:
        assert item.input_schema["type"] == "object", item.spec.name
        assert item.input_schema["additionalProperties"] is False, item.spec.name
        assert isinstance(item.input_schema["properties"], dict), item.spec.name
        assert isinstance(item.input_schema["required"], list), item.spec.name
        assert item.output_schema, item.spec.name
        jsonschema.Draft202012Validator.check_schema(dict(item.input_schema))
        jsonschema.Draft202012Validator.check_schema(dict(item.output_schema))


@pytest.mark.parametrize(
    ("tool_name", "argument", "model_name", "discriminator", "variant_count"),
    [
        ("apply_edits", "operations", "EditOperation", "type", 10),
        ("apply_table_ops", "ops", "TableOperation", "op", 12),
        ("apply_body_ops", "ops", "BodyOperation", "op", 6),
    ],
)
def test_public_mutation_batches_are_closed_discriminated_unions(
    tool_name, argument, model_name, discriminator, variant_count
):
    schema = bound_tool_registry().by_name()[tool_name].input_schema
    assert schema["properties"][argument]["items"] == {"$ref": f"#/$defs/{model_name}"}
    union = schema["$defs"][model_name]
    assert union["discriminator"]["propertyName"] == discriminator
    assert len(union["oneOf"]) == variant_count
    for ref in union["oneOf"]:
        variant = schema["$defs"][ref["$ref"].rsplit("/", 1)[-1]]
        assert variant["additionalProperties"] is False


def test_contract_payload_is_deterministic_and_contains_bound_schemas():
    first = contract_payload()
    second = contract_payload()
    assert first == second
    assert first["minAutomationVersion"] == first["minMcpVersion"] == "7.1.0"
    assert len(first["tools"]) == 136
    assert all(tool["inputSchema"] and tool["outputSchema"] for tool in first["tools"])
