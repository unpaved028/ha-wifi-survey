# WiFi Survey for Home Assistant

Plan your WiFi with your own floor plans, right inside Home Assistant.

[![Add the WiFi Survey repository to your Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Funpaved028%2Fha-wifi-survey)

1. Click the button above (or add `https://github.com/unpaved028/ha-wifi-survey` under Settings → Apps → Install app → ⋮ → Repositories).
2. Install **WiFi Survey** and start it. It appears in the sidebar.
3. On the Start page, upload a floor plan, or load the example house to look around first.

## What it does

- **Floor plans:** upload a PDF or image, cut out the floors, set the scale. Walls are detected automatically (hatched, filled, light grey or outline only) and can be corrected in an editor.
- **Coverage maps** for 2.4 and 5 GHz on every floor and across floors, calibrated with your measurements.
- **Simulation and recommendations:** move, switch off or add repeaters and see the effect; let the app suggest better spots.
- **Device finder:** where is the phone? The app lists the most likely rooms. Room names come from your Home Assistant areas.
- **Measuring:** measurement runs read the FRITZ!Box mesh and Shelly devices; the included Android app records all access points where you stand.

Full support (measurement runs, device finder) needs a FRITZ!Box. With other routers you can plan and measure with the Android app. The user interface is in German for now; English is on its way.

## Privacy

Everything stays in your home network. The app only reads from the FRITZ!Box, Shelly devices and Home Assistant and never writes to them. Projects are part of your Home Assistant backups.

## Development

```bash
uv sync
uv run pytest -q
uv run wifi-survey serve     # http://127.0.0.1:8770, data in ./data
```

The app folder is `wifi_survey/`; images for aarch64 and amd64 are built by GitHub Actions and published to `ghcr.io/unpaved028/wifi-survey`.

## License

MIT, see [LICENSE](LICENSE). FRITZ!Box is a trademark of AVM; Shelly is a trademark of Shelly Group. This project is not affiliated with them or with Home Assistant.
