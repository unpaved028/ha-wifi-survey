# Änderungen

## 1.5.0
- New name: **WiFi Survey** (before: WLAN-Ausleuchtung). Documentation in English and German. / Neuer Name: **WiFi Survey** (vorher WLAN-Ausleuchtung), Doku auf Englisch und Deutsch
- Preparation for publishing in Home Assistant (public app repository with prebuilt images) / Vorbereitung der Veröffentlichung (öffentliches App-Repository mit vorgebauten Abbildern)

## 1.4.0
- Beispielhaus: In einem leeren Projekt lädt „Start“ ein erzeugtes Haus mit zwei Stockwerken, Router, Repeater, Messpunkten, benannten Räumen und Geräten zum Suchen. So lässt sich die App ohne eigenen Plan und ohne FRITZ!Box ausprobieren. Im Beispiel sind Messlauf und Messen aus; „Beispiel beenden“ leert das Projekt wieder

## 1.3.1
- Räume: Stehen Geräte eines Bereichs in zwei Räumen, heißt der zweite z. B. „Büro 2“

## 1.3.0
- Suchen nach Räumen: Die Suche nennt die wahrscheinlichsten Räume der Reihe nach („Wo zuerst nachsehen“) und zeichnet sie im Plan ein. In der Kreuzprobe mit einem echten Haus lag der richtige Raum mit dem Scan der App in 8 von 10 Fällen unter den ersten zwei
- Räume erkennt die App aus den Wänden (Türöffnungen bis 1,2 m gelten als zu). Namen kommen aus den Bereichen der Geräte in Home Assistant; im Editor (Werkzeug „Räume“, Taste R) lassen sie sich ändern
- „findbar“: Hat sich das Signal an der FRITZ!Box seit der Meldung des Handys deutlich geändert, gilt die Meldung als überholt; die Suche sagt das und rechnet mit dem Wert der FRITZ!Box
- Fundorte merken sich, auf welchem Platz ihr Raum in der Liste stand

## 1.2.1
- Editor: Die Werkzeug-Knöpfe passen wieder vollständig in die Seitenleiste (rechte Spalte war abgeschnitten)
- Dunkel-Modus auf iPhone und iPad (Safari): Der Plan liegt jetzt auch dort auf gedämpftem Papier statt grellweiß; Farben im Plan sind für ältere Safari-Versionen zusätzlich abgesichert

## 1.2.0
- Darstellungen: oben rechts zwischen Automatisch, Hell, Dunkel und Classic (bisheriges Aussehen) wählen. Hell und Dunkel sind an Home Assistant angelehnt; Automatisch folgt in der Seitenleiste von Home Assistant dessen Modus, sonst dem System. Im Dunkel-Modus liegt der Plan auf gedämpftem Papier
- Bedienung: Beschriftungen der Zugangspunkte überlappen nicht mehr; in der Auswertung stehen Karte und Hinweise vor Simulation und Empfehlung; kompaktere Seitenleiste im Editor mit Symbolen; Geräte-Namen im Plan ausblendbar; Griffe der Wandenden nur bei Einzelauswahl; auf dem Handy größere Knöpfe, kürzere Hinweise und der aktive Reiter bleibt sichtbar; in der 3D-Suche „Drehung zurücksetzen“
- Messen: 0 dBm aus älteren Rundgängen (Platzhalter von Android) erscheint nicht mehr als stärkster Wert eines Messpunkts

## 1.1.0
- Wanderkennung für weitere Zeichenstile: hellgrau gefüllte Wände mit dünnem Rand (Exposés) und Wände nur als Umrisslinien (CAD-Pläne); Auswahl „Wände im Plan“ im Editor, falls die Automatik danebenliegt

## 1.0.0
- Neue Ansicht „Start“: geführter Ablauf vom Plan bis zur Auswertung, mit dem Stand des Projekts je Schritt; der nächste offene Schritt führt direkt an die richtige Stelle. Ohne Plan öffnet die App dort

## 0.9.0
- 5 GHz mit eigenem Modell (Wände, Decken, Zugangspunkte getrennt geeicht): In der Auswertung unter „Karte“ zwischen 2,4 und 5 GHz wählen; Karte, Abdeckung und Tabelle „Haus“ folgen dem Band
- Suchen: Werte auf 5 GHz nutzen das 5-GHz-Modell; der Suchbereich mit dem Scan des Handys ist ehrlicher (Mindest-Unsicherheit 8 statt 6 dB, aus einer Kreuzprobe mit 40 Messpunkten)

## 0.8.0
- Messen ohne FRITZ!Box: In der Ansicht „Messen“ die Netze aus dem Scan des Handys eigenen Routern und Repeatern zuordnen; Messpunkte zählen dann auch für sie

## 0.7.0
- Planung ohne Messlauf: Router, Repeater, Zugangspunkte per LAN und sonstige Geräte als eigene Geräte platzieren (Werkzeug „Geräte“), umbenennen und die Art ändern. Auswertung, Simulation und Empfehlung rechnen ohne Messlauf mit Startwerten

## 0.6.0
- Auswertung: Anbindung der Repeater per WLAN aus der Mesh-Liste (Signal je Band in beide Richtungen) und die Einschätzung von FRITZ!OS zum Platz („zu nah“, „in Ordnung“, „zu weit weg“), mit Hinweisen. Erscheint nach „Neu messen“
- Simulation und Empfehlung: Die Anbindung eines verschobenen Repeaters rechnet vom gemessenen Signal aus statt nur mit dem Modell

## 0.5.0
- Hausfläche je Stockwerk im Editor (Werkzeug „Hausfläche“, Taste H): Vorschlag der Automatik übernehmen, neu zeichnen oder vom ausgerichteten Stockwerk übernehmen; Ecken ziehen, einfügen, löschen. Abdeckung und Suche rechnen mit dieser Fläche
- Karten reichen bis zu Messpunkten, Fundorten und Umriss, auch wenn dort keine Wände gezeichnet sind

## 0.4.1
- „findbar“: Der Server verwarf Scan-Ergebnisse, die älter als eine Minute waren. Im Hintergrund nutzt die App aber vorhandene Ergebnisse aus der Ruhephase; übrig blieb oft nur der verbundene Zugangspunkt. Jetzt gelten bis zu 35 Minuten
- Suchen: Ein Scan zählt erst ab zwei Zugangspunkten; die Ansicht zeigt, welche Zugangspunkte das Handy gemeldet hat

## 0.4.0
- Hintergrundmodus „findbar“ für die Android-App (Version 0.2.0): Das ruhende Handy meldet einen WLAN-Scan; die Suche rechnet dann mit allen Zugangspunkten statt mit einem
- Fundort nach einer Suche mit Scan: Der Scan zählt dort als vollständiger Messpunkt

## 0.3.1
- Messpunkte: Platzhalter-Werte aus dem Scan von Android (0 dBm) werden verworfen; sie verdrängten echte Werte und verzerrten das Modell
- Hausfläche: Fehlen Außenwände, reicht die geschätzte Fläche bis zu Messpunkten und Fundorten; um jeden Messpunkt und Fundort zählt 1 m als innen
- Suchen: Unsicherheit mindestens 8 dB (Kreuzprobe mit Fundorten und Shellys)

## 0.3.0
- Gerät im Haus suchen: Wahrscheinlichkeit über alle Stockwerke aus dem Signal an seinem Zugangspunkt, Haus in 3D; gemeldete Fundorte eichen das Modell
- Modell: Abgleich für die Sicht der FRITZ!Box und 5-GHz-Abschlag

## 0.2.0
- Erste Fassung als Home-Assistant-App: Oberfläche über Ingress in der Seitenleiste, Zugang zu Home Assistant über den Supervisor, FRITZ!Box-Zugang in der Konfiguration
- Projekt exportieren und importieren (ZIP)
- Direktzugriff für die Android-App über einen freigebbaren Port
