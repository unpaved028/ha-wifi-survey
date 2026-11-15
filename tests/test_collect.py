"""Sammler: Funkstrecken zwischen Zugangspunkten aus der Mesh-Liste."""

from wifi_survey.collect import access_points, mesh_links, wlan_clients


def mesh():
    """FRITZ!Box mit einem Repeater (per WLAN auf 2,4 und 5 GHz) und einem Handy.

    Reihenfolge der Knoten wie in einer echten Mesh-Liste: auf 2,4 GHz ist der Repeater node_1, auf 5 GHz die FRITZ!Box."""
    box_if = [{"uid": "b24", "name": "AP:2G:0", "type": "WLAN", "ssid": "WLAN", "mac_address": "02:12:37:9C:0F:B7",
               "node_links": []},
              {"uid": "b5", "name": "AP:5G:0", "type": "WLAN", "ssid": "WLAN", "mac_address": "02:12:37:9C:0F:B6",
               "node_links": []}]
    rep_if = [{"uid": "r24", "name": "UPLINK:2G:0", "type": "WLAN", "ssid": "", "node_links": [],
               "client_position": "too_close"},
              {"uid": "r5", "name": "UPLINK:5G:0", "type": "WLAN", "ssid": "", "node_links": [], "client_position": "ok"}]
    links = [
        {"uid": "l1", "type": "WLAN", "state": "CONNECTED", "node_1_uid": "rep", "node_2_uid": "box",
         "node_interface_1_uid": "r24", "node_interface_2_uid": "b24", "rx_rcpi": -26, "tx_rcpi": -32},
        {"uid": "l2", "type": "WLAN", "state": "CONNECTED", "node_1_uid": "box", "node_2_uid": "rep",
         "node_interface_1_uid": "b5", "node_interface_2_uid": "r5", "rx_rcpi": -39, "tx_rcpi": 255},
        {"uid": "l3", "type": "WLAN", "state": "CONNECTED", "node_1_uid": "box", "node_2_uid": "phone",
         "node_interface_1_uid": "b5", "node_interface_2_uid": "p0", "rx_rcpi": -60, "tx_rcpi": 255},
    ]
    for link in links:   # wie in der Mesh-Liste: jede Verbindung bei beiden Schnittstellen
        for i in box_if + rep_if:
            if i["uid"] in (link["node_interface_1_uid"], link["node_interface_2_uid"]):
                i["node_links"].append(link)
    return {"nodes": [
        {"uid": "box", "device_name": "fritz.box", "mesh_role": "master", "device_mac_address": "02:12:37:9C:0F:B4",
         "node_interfaces": box_if},
        {"uid": "rep", "device_name": "OG-Bad", "mesh_role": "slave", "device_mac_address": "02:D6:C6:CE:25:C2",
         "node_interfaces": rep_if},
        {"uid": "phone", "device_name": "Pixel", "mesh_role": "unknown", "device_mac_address": "AA:BB:CC:DD:EE:FF",
         "node_interfaces": [{"uid": "p0", "name": "", "type": "WLAN", "node_links": [links[2]]}]},
    ]}


def test_mesh_links_directions_and_bands():
    m = mesh()
    got = sorted((x["from"], x["to"], x["band"], x["rssi"]) for x in mesh_links(m))
    box, rep = "02:12:37:9C:0F:B4", "02:D6:C6:CE:25:C2"
    assert got == sorted([(box, rep, "2.4", -26),      # node_1 (Repeater) empfängt die FRITZ!Box
                          (rep, box, "2.4", -32),
                          (rep, box, "5", -39)]), got  # 255 = unbekannt, Handy zählt nicht
    assert [c["name"] for c in wlan_clients(m)] == ["Pixel"]
    aps = access_points(m)
    assert [a["name"] for a in aps] == ["fritz.box", "OG-Bad"]
    assert aps[1]["uplink_position"] == {"2.4": "too_close", "5": "ok"} and aps[0]["uplink_position"] == {}
