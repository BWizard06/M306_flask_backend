from flask import Flask, request, jsonify
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app)


def xml_file_to_string(xml_file_path):
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    return ET.tostring(root, encoding='unicode')


def verarbeite_xml(dateipfad):
    xml_data = xml_file_to_string(dateipfad)
    root = ET.fromstring(xml_data)
    
    start_time_str = root.find(".//rsm:StartDateTime", namespaces={"rsm": "http://www.strom.ch"}).text
    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
    doc_id: str = root.find(".//rsm:DocumentID", namespaces={"rsm": "http://www.strom.ch"}).text[-5::]
    
    results = []
    for obs in root.findall(".//rsm:Observation", namespaces={"rsm": "http://www.strom.ch"}):
        sequence = int(obs.find("./rsm:Position/rsm:Sequence", namespaces={"rsm": "http://www.strom.ch"}).text)
        
        if doc_id == 'ID742':
            volume_bezug = float(obs.find("./rsm:Volume", namespaces={"rsm": "http://www.strom.ch"}).text)
            volume_geben = 0
        elif doc_id == 'ID735':
            volume_geben = float(obs.find("./rsm:Volume", namespaces={"rsm": "http://www.strom.ch"}).text)
            volume_bezug = 0

        timestamp = start_time + timedelta(minutes=15 * (sequence - 1))
        formatted_timestamp = timestamp.strftime("%d.%m.%Y %H:%M")
        
        results.append({
            "timestamp": formatted_timestamp,
            "value_bezug": volume_bezug,
            "value_geben": volume_geben
        })
    
    return results


def verarbeite_xml_verzeichnis(verzeichnis):
    gesamt_ergebnis_dict = {}

    for dateiname in os.listdir(verzeichnis):
        if dateiname.endswith('.xml'):
            dateipfad = os.path.join(verzeichnis, dateiname)
            ergebnisse = verarbeite_xml(dateipfad)

            for ergebnis in ergebnisse:
                timestamp = ergebnis["timestamp"]
                if timestamp not in gesamt_ergebnis_dict:
                    gesamt_ergebnis_dict[timestamp] = {"timestamp": timestamp, "value_bezug": 0, "value_geben": 0}

                if ergebnis["value_bezug"] != 0:
                    gesamt_ergebnis_dict[timestamp]["value_bezug"] = ergebnis["value_bezug"]

                if ergebnis["value_geben"] != 0:
                    gesamt_ergebnis_dict[timestamp]["value_geben"] = ergebnis["value_geben"]

    return list(gesamt_ergebnis_dict.values())


@app.route('/')
def hello_world():
    with open('index.html', 'r') as file:
        return file.read()

@app.route('/sdat')
def sdat():
    verzeichnis = request.args.get('verzeichnis')
    return jsonify(verarbeite_xml_verzeichnis(verzeichnis))


if __name__ == '__main__':
    app.run(debug=True)
