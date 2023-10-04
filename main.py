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

def calculate_cumulative_values(sdat_list, initial_values):
    cumulative_bezug = initial_values['value_bezug']
    cumulative_geben = initial_values['value_geben']
    
    for entry in sdat_list:
        cumulative_bezug += entry['value_bezug']
        cumulative_geben += entry['value_geben']

        entry['value_bezug'] = cumulative_bezug
        entry['value_geben'] = cumulative_geben
        
    return sdat_list


def verarbeite_xml_sdat(dateipfad):
    xml_data = xml_file_to_string(dateipfad)
    root = ET.parse(dateipfad).getroot()
    
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


def verarbeite_xml_verzeichnis_sdat(verzeichnis):
    gesamt_ergebnis_dict = {}

    for dateiname in os.listdir(verzeichnis):
        if dateiname.endswith('.xml'):
            dateipfad = os.path.join(verzeichnis, dateiname)
            ergebnisse = verarbeite_xml_sdat(dateipfad)

            for ergebnis in ergebnisse:
                timestamp = ergebnis["timestamp"]
                if timestamp not in gesamt_ergebnis_dict:
                    gesamt_ergebnis_dict[timestamp] = {"timestamp": timestamp, "value_bezug": 0, "value_geben": 0}

                if ergebnis["value_bezug"] != 0:
                    gesamt_ergebnis_dict[timestamp]["value_bezug"] = ergebnis["value_bezug"]

                if ergebnis["value_geben"] != 0:
                    gesamt_ergebnis_dict[timestamp]["value_geben"] = ergebnis["value_geben"]

    return list(gesamt_ergebnis_dict.values())


def verarbeite_esl_verzeichnis(verzeichnis):
    gesamt_ergebnis_dict = {}

    for dateiname in os.listdir(verzeichnis):
        if dateiname.endswith('.xml'):
            dateipfad = os.path.join(verzeichnis, dateiname)
            ergebnisse = verarbeite_esl_xml(dateipfad)

            for ergebnis in ergebnisse:
                timestamp = ergebnis["timestamp"]
                if timestamp not in gesamt_ergebnis_dict:
                    gesamt_ergebnis_dict[timestamp] = {"timestamp": timestamp, "value_bezug": 0, "value_geben": 0}

                gesamt_ergebnis_dict[timestamp]["value_bezug"] += ergebnis["value_bezug"]
                gesamt_ergebnis_dict[timestamp]["value_geben"] += ergebnis["value_geben"]

    return list(gesamt_ergebnis_dict.values())


def verarbeite_esl_xml(dateipfad):
    tree = ET.parse(dateipfad)
    root = tree.getroot()
    
    results = []
    
    for meter in root.findall('.//Meter'):
        for time_period in meter.findall('.//TimePeriod'):
            time_period_end = time_period.get('end')
            bezug_1, bezug_2, geben_1, geben_2 = 0, 0, 0, 0

            for value_row in time_period.findall('.//ValueRow'):
                obis = value_row.get('obis')
                value = float(value_row.get('value', '0'))
                
                if obis == "1-1:1.8.1":
                    bezug_1 = value
                elif obis == "1-1:1.8.2":
                    bezug_2 = value
                elif obis == "1-1:2.8.1":
                    geben_1 = value
                elif obis == "1-1:2.8.2":
                    geben_2 = value

            total_bezug = bezug_1 + bezug_2
            total_geben = geben_1 + geben_2
            
            results.append({
                "timestamp": time_period_end,
                "value_bezug": total_bezug,
                "value_geben": total_geben
            })
    
    return results

@app.route('/')
def hello_world():
    with open('index.html', 'r') as file:
        return file.read()

@app.route('/sdat')
def sdat():
    verzeichnis = request.args.get('sdat')
    return jsonify(verarbeite_xml_verzeichnis_sdat(verzeichnis))


@app.route('/esl')
def esl():
    sdat_path = request.args.get('sdat')
    esl_path = request.args.get('esl')
    
    sdat_data = verarbeite_xml_verzeichnis_sdat(sdat_path)
    esl_data = verarbeite_esl_verzeichnis(esl_path)
    
    # ESL-Daten sortieren, um den benötigten Anfangswert für den entsprechenden Monat zu finden
    sorted_esl_data = sorted(esl_data, key=lambda x: datetime.fromisoformat(x["timestamp"].replace('T', ' ').replace('Z', '')))
    
    # Den initialen Wert aus den ESL-Daten für den entsprechenden Monat extrahieren
    initial_month = datetime.fromisoformat(sdat_data[0]['timestamp'].replace('T', ' ').replace('Z', '')).month

    initial_values = next((entry for entry in sorted_esl_data if datetime.fromisoformat(entry["timestamp"].replace('T', ' ').replace('Z', '')).month == initial_month), None)


    if not initial_values:
        return jsonify({"error": "Keine passenden ESL-Daten für den gegebenen Monat gefunden!"}), 400
    
    combined_data = calculate_cumulative_values(sdat_data, initial_values)
    
    return jsonify(combined_data)


if __name__ == '__main__':
    app.run(debug=True)



"""
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


def verarbeite_xml_sdat(dateipfad):
    xml_data = xml_file_to_string(dateipfad)
    root = ET.parse(dateipfad).getroot()
    
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


def verarbeite_xml_verzeichnis_sdat(verzeichnis):
    gesamt_ergebnis_dict = {}

    for dateiname in os.listdir(verzeichnis):
        if dateiname.endswith('.xml'):
            dateipfad = os.path.join(verzeichnis, dateiname)
            ergebnisse = verarbeite_xml_sdat(dateipfad)

            for ergebnis in ergebnisse:
                timestamp = ergebnis["timestamp"]
                if timestamp not in gesamt_ergebnis_dict:
                    gesamt_ergebnis_dict[timestamp] = {"timestamp": timestamp, "value_bezug": 0, "value_geben": 0}

                if ergebnis["value_bezug"] != 0:
                    gesamt_ergebnis_dict[timestamp]["value_bezug"] = ergebnis["value_bezug"]

                if ergebnis["value_geben"] != 0:
                    gesamt_ergebnis_dict[timestamp]["value_geben"] = ergebnis["value_geben"]

    return list(gesamt_ergebnis_dict.values())


def verarbeite_esl_verzeichnis(verzeichnis):
    gesamt_ergebnis_dict = {}

    for dateiname in os.listdir(verzeichnis):
        if dateiname.endswith('.xml'):
            dateipfad = os.path.join(verzeichnis, dateiname)
            ergebnisse = verarbeite_esl_xml(dateipfad)

            for ergebnis in ergebnisse:
                timestamp = ergebnis["timestamp"]
                if timestamp not in gesamt_ergebnis_dict:
                    gesamt_ergebnis_dict[timestamp] = {"timestamp": timestamp, "value_bezug": 0, "value_geben": 0}

                gesamt_ergebnis_dict[timestamp]["value_bezug"] += ergebnis["value_bezug"]
                gesamt_ergebnis_dict[timestamp]["value_geben"] += ergebnis["value_geben"]

    return list(gesamt_ergebnis_dict.values())


def verarbeite_esl_xml(dateipfad):
    tree = ET.parse(dateipfad)
    root = tree.getroot()
    
    results = []
    
    for meter in root.findall('.//Meter'):
        for time_period in meter.findall('.//TimePeriod'):
            time_period_end = time_period.get('end')
            bezug_1, bezug_2, geben_1, geben_2 = 0, 0, 0, 0

            for value_row in time_period.findall('.//ValueRow'):
                obis = value_row.get('obis')
                value = float(value_row.get('value', '0'))
                
                if obis == "1-1:1.8.1":
                    bezug_1 = value
                elif obis == "1-1:1.8.2":
                    bezug_2 = value
                elif obis == "1-1:2.8.1":
                    geben_1 = value
                elif obis == "1-1:2.8.2":
                    geben_2 = value

            total_bezug = bezug_1 + bezug_2
            total_geben = geben_1 + geben_2
            
            results.append({
                "timestamp": time_period_end,
                "value_bezug": total_bezug,
                "value_geben": total_geben
            })
    
    return results

@app.route('/')
def hello_world():
    with open('index.html', 'r') as file:
        return file.read()

@app.route('/sdat')
def sdat():
    verzeichnis = request.args.get('sdat')
    return jsonify(verarbeite_xml_verzeichnis_sdat(verzeichnis))


@app.route('/esl')
def esl():
    #sdat = request.args.get('sdat')
    esl = request.args.get('esl')

    #return jsonify(verarbeite_xml_verzeichnis_sdat(sdat))
    return jsonify(verarbeite_esl_verzeichnis(esl))


if __name__ == '__main__':
    app.run(debug=True)



"""