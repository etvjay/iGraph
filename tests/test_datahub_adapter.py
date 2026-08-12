from types import SimpleNamespace

from igraph.datahub_adapter import DataHubAdapter


def test_structured_properties_accept_sdk_assignment_lists():
    value = [
        SimpleNamespace(
            propertyUrn="urn:li:structuredProperty:lifecycle",
            values=["production"],
        ),
        {"propertyUrn": "urn:li:structuredProperty:priority", "values": [1, 2]},
    ]

    assert DataHubAdapter._structured_properties(value) == {
        "urn:li:structuredProperty:lifecycle": "production",
        "urn:li:structuredProperty:priority": "1, 2",
    }
