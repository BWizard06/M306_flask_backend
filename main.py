from flask import Flask, request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from flask_cors import CORS

import os

def verarbeite_xml_verzeichnis(verzeichnis):
    gesamt_ergebnis = []
    
    for dateiname in os.listdir(verzeichnis):
        if dateiname.endswith('.xml'):
            dateipfad = os.path.join(verzeichnis, dateiname)
            ergebnis = verarbeite_xml(dateipfad)
            gesamt_ergebnis.extend(ergebnis)
    
    return gesamt_ergebnis

def xml_file_to_string(xml_file_path):
    # XML-Datei laden
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    
    # XML-Inhalt zum String umwandeln
    return ET.tostring(root, encoding='unicode')

# XML-Daten als string
def verarbeite_xml(dateipfad):
    xml_data = xml_file_to_string(dateipfad)

# XML-Daten parsen
    root = ET.fromstring(xml_data)

# Startzeitpunkt auslesen
    start_time_str = root.find(".//rsm:StartDateTime", namespaces={"rsm": "http://www.strom.ch"}).text
    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))

# Ergebnisliste erstellen
    result = []

# Durch die "Observation"-Tags iterieren
    for obs in root.findall(".//rsm:Observation", namespaces={"rsm": "http://www.strom.ch"}):
    # Sequenz und Volumen auslesen
        sequence = int(obs.find("./rsm:Position/rsm:Sequence", namespaces={"rsm": "http://www.strom.ch"}).text)
        volume = obs.find("./rsm:Volume", namespaces={"rsm": "http://www.strom.ch"}).text

    # Timestamp berechnen
        timestamp = start_time + timedelta(minutes=15 * (sequence - 1))

        formatted_timestamp = timestamp.timestamp() * 1000

    # Ergebnis hinzufügen
        result.append({
        "timestamp": formatted_timestamp,
        "value": volume
    })

    return(result)


app = Flask(__name__)

CORS(app)

@app.route('/')
def hello_world():
    return 'Hello, World!'

@app.route('/sdat')
def sdat():
    verzeichnis = request.args.get('verzeichnis')
    return verarbeite_xml_verzeichnis(verzeichnis)


if __name__ == '__main__':
    app.run(debug=True)