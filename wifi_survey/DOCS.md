# WiFi Survey

*Deutsch weiter unten.*

Open the app from the Home Assistant sidebar ("WiFi Survey"). The **Start** view guides you step by step and shows what is still open:

1. Upload a floor plan (PDF or image) and cut out the floors.
2. Set the scale, let the app detect the walls and correct them. It recognizes hatched, filled, light grey and outline-only walls; under "Wände im Plan" you can choose the style.
3. Place router, repeaters and devices: from a FRITZ!Box measurement run or as your own devices, e.g. for planning without measurements.
4. Check the house area (tool "Hausfläche"), especially under sloped roofs.
5. Align the floors on top of each other.
6. Look at the coverage per floor for 2.4 and 5 GHz, move repeaters in the simulation and let the app recommend better spots.

Without measurements the app uses default values. Measurement runs (FRITZ!Box, Shellys) and walks with the Android app make the maps more accurate.

No plan at hand? In an empty project the Start view loads an **example house** with two floors, router, repeater, measurements and devices to find. "Beispiel beenden" empties the project again.

**Device finder ("Suchen"):** The app estimates where a WiFi device is, for example a misplaced phone, and lists the most likely rooms first. Rooms come from the walls; their names come from the areas of your devices in Home Assistant, and you can rename them (tool "Räume"). Each reported find improves the next estimate. With a single value from the FRITZ!Box the result is a ring around the access point; phones with the Android app ("findbar") report all access points and are found more precisely.

## Configuration

| Option | Meaning |
|---|---|
| FRITZ!Box address | Host name or IP address of the FRITZ!Box that controls the mesh (default `fritz.box`) |
| FRITZ!Box user, password | Access for measurement runs via TR-064. On the FRITZ!Box enable "Allow access for applications" (Home Network → Network → Network Settings) and create a separate user |

A measurement run reads the mesh overview and the device list of the FRITZ!Box and asks Shelly devices in your network for their WiFi status and WiFi scan. **The app never writes to the FRITZ!Box or to Shelly devices.**

Device names and areas come from Home Assistant through the Supervisor, without an extra token. That is why the app asks for access to the Home Assistant API (`homeassistant_api`); access to the Supervisor (`hassio_api`) is used for this connection and for information about the app itself.

## Measuring with a phone

The Android app (view "Messen" → download) records the signal of all access points where you stand. It needs a direct address in your home network because it does not go through the Home Assistant login:

1. Enter a port under **Network**, e.g. `8770`, and restart the app.
2. In the Android app enter `http://<IP of Home Assistant>:8770` as server. The view "Messen" shows the address.

Through this port the user interface is reachable **without login** in your home network. Leave the field empty if you do not measure with a phone.

Without a FRITZ!Box: create your own router and repeaters with the tool "Geräte". In "Messen" you assign the networks from the phone's scan to them; only the addresses (BSSID) of these networks are stored.

**findbar:** In "Messen" a phone can be made findable. When it lies still for a few minutes, the Android app reports a WiFi scan in the background, and the device finder uses all access points.

## Data

Project (plans, floors, walls, devices, measurement points) and measurement runs are stored in the app's data folder and are part of the Home Assistant backups. Everything stays in your home network.

In the view "Pläne" under **Projekt** you can export the project as a ZIP file and import it again. On import the previous project is kept in the data folder under `sicherungen/`.

## Limitations

- The user interface is in German for now; English is on its way.
- Full support (measurement runs, device finder) needs a FRITZ!Box. With other routers you can plan and measure with the Android app.
- The device finder is accurate to about one room: in tests the right room was among the first two in about 8 out of 10 cases.

## Help and license

Questions and bugs: [GitHub issues](https://github.com/unpaved028/ha-wifi-survey/issues). License: MIT.

---

# WiFi Survey (Deutsch)

Die Oberfläche öffnest du über die Seitenleiste von Home Assistant („WiFi Survey“). Die Ansicht **Start** führt Schritt für Schritt durch das Projekt und zeigt, was noch offen ist:

1. Grundriss hochladen (PDF oder Bild) und Stockwerke als Ausschnitte festlegen.
2. Maßstab setzen, Wände erkennen lassen und korrigieren. Erkannt werden schraffierte, gefüllte, hellgraue und nur als Umriss gezeichnete Wände; unter „Wände im Plan“ lässt sich der Stil vorgeben.
3. Router, Repeater und Geräte platzieren: aus dem Messlauf der FRITZ!Box oder als eigene Geräte, etwa zur Planung ohne Messung.
4. Hausfläche prüfen (Werkzeug „Hausfläche“), besonders unter Dachschrägen.
5. Stockwerke übereinander ausrichten.
6. In der Auswertung die Abdeckung je Stockwerk für 2,4 und 5 GHz ansehen, Repeater in der Simulation verschieben und bessere Plätze empfehlen lassen.

Ohne Messung rechnet die App mit Startwerten. Messläufe (FRITZ!Box, Shellys) und Rundgänge mit der Android-App machen die Karten genauer.

Kein Plan zur Hand? In einem leeren Projekt lädt „Start“ ein **Beispielhaus** mit zwei Stockwerken, Router, Repeater, Messwerten und Geräten zum Suchen. „Beispiel beenden“ leert das Projekt wieder.

**Suchen:** Die App schätzt, wo ein WLAN-Gerät liegt, etwa ein verlegtes Handy, und nennt die wahrscheinlichsten Räume zuerst. Räume entstehen aus den Wänden. Ihre Namen kommen aus den Bereichen deiner Geräte in Home Assistant und lassen sich ändern (Werkzeug „Räume“). Jeder gemeldete Fundort macht die nächste Schätzung genauer. Mit nur einem Wert der FRITZ!Box ergibt sich ein Ring um den Zugangspunkt. Handys mit der Android-App („findbar“) melden alle Zugangspunkte und werden genauer gefunden.

## Konfiguration

| Option | Bedeutung |
|---|---|
| FRITZ!Box-Adresse | Name oder IP der FRITZ!Box, die das Mesh steuert (Standard `fritz.box`) |
| FRITZ!Box-Benutzer, -Passwort | Zugang für den Messlauf über TR-064. In der FRITZ!Box „Zugriff für Anwendungen zulassen“ einschalten (Heimnetz → Netzwerk → Netzwerkeinstellungen) und einen eigenen Benutzer anlegen |

Der Messlauf liest die Mesh-Übersicht und die Geräteliste der FRITZ!Box und fragt Shellys im Heimnetz nach ihrem WLAN-Status und ihrem WLAN-Scan. **Die App schreibt nichts auf FRITZ!Box oder Shellys.**

Namen und Bereiche der Geräte holt die App aus Home Assistant, über den Supervisor und ohne eigenes Token. Deshalb fragt sie nach Zugriff auf die HA-API (`homeassistant_api`). Den Zugang zum Supervisor (`hassio_api`) nutzt sie dafür und für Angaben zur eigenen App.

## Messen mit dem Handy

Die Android-App (Ansicht „Messen“ → herunterladen) misst das Signal aller Zugangspunkte dort, wo du stehst. Sie braucht eine direkte Adresse im Heimnetz, weil sie nicht über die Anmeldung von Home Assistant geht:

1. Hier unter **Netzwerk** einen Port eintragen, z. B. `8770`, und die App neu starten.
2. In der Android-App als Server `http://<IP von Home Assistant>:8770` eintragen. Die Ansicht „Messen“ zeigt die Adresse an.

Über diesen Port ist die Oberfläche **ohne Anmeldung** im Heimnetz erreichbar. Lass das Feld leer, wenn du nicht mit dem Handy misst.

Ohne FRITZ!Box: Eigene Router und Repeater im Werkzeug „Geräte“ anlegen. In „Messen“ ordnest du ihnen die Netze aus dem Scan des Handys zu; gespeichert werden nur die Adressen (BSSID) dieser Netze.

**findbar:** In „Messen“ lässt sich das Handy findbar machen. Liegt es einige Minuten still, meldet die Android-App im Hintergrund einen WLAN-Scan; „Suchen“ rechnet dann mit allen Zugangspunkten.

## Daten

Projekt (Pläne, Stockwerke, Wände, Geräte, Messpunkte) und Messläufe liegen im Datenordner der App und sind Teil der Sicherungen von Home Assistant. Alles bleibt im Heimnetz.

In der Ansicht „Pläne“ unter **Projekt** lässt sich das Projekt als ZIP-Datei exportieren und wieder importieren. Beim Import bleibt das bisherige Projekt im Datenordner unter `sicherungen/` erhalten.

## Grenzen

- Die Oberfläche ist vorerst deutsch, Englisch folgt.
- Voll unterstützt (Messlauf, Suche) wird die FRITZ!Box. Mit anderen Routern gehen Planung und Messen mit der Android-App.
- Die Suche ist etwa auf einen Raum genau: In Tests lag der richtige Raum in etwa 8 von 10 Fällen unter den ersten zwei.

## Hilfe und Lizenz

Fragen und Fehler: [GitHub-Issues](https://github.com/unpaved028/ha-wifi-survey/issues). Lizenz: MIT.
