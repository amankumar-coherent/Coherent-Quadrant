import json

from vendor_intel.quadrant.viewer import render_viewer


def test_viewer_embeds_payload_with_capability_titles():
    payload = {"market": "X Market", "axis_titles": {"x": "Service Capability", "y": "Business Capability"},
               "criteria": {"axis_labels": {"x": "Product Strength", "y": "Business Strength"}},
               "brands": [{"company": "A", "note": "</script>"}]}
    html = render_viewer(payload)
    blob = html.split('id="quadrant-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    data = json.loads(blob.replace("<\/", "</"))
    assert data["criteria"]["axis_labels"] == {"x": "Service Capability", "y": "Business Capability"}
    assert data["brands"][0]["note"] == "</script>"
    assert "__QUADRANT_DATA__" not in html
    assert 'class="dots" title=' not in html  # long-tail bubbles: no tooltip
