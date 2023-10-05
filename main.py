from flask import Flask, request, jsonify
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from flask_cors import CORS
import os


app = Flask(__name__, static_folder = 'static')
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
    added_timestamps = set()  # Dieses Set speichert die Zeitstempel der bereits hinzugefügten Daten
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
        
        # Überprüfen, ob der Zeitstempel bereits hinzugefügt wurde
        if formatted_timestamp not in added_timestamps:
            results.append({
                "timestamp": formatted_timestamp,
                "value_bezug": volume_bezug,
                "value_geben": volume_geben
            })
            added_timestamps.add(formatted_timestamp)
    
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

    # Hier sortieren wir die Ergebnisse nach dem Zeitstempel.
    gesamt_ergebnis_liste = list(gesamt_ergebnis_dict.values())
    gesamt_ergebnis_liste.sort(key=lambda x: datetime.strptime(x["timestamp"], "%d.%m.%Y %H:%M"))

    return gesamt_ergebnis_liste



def verarbeite_esl_verzeichnis(verzeichnis):
    gesamt_ergebnis_dict = {}
    earliest_timestamp = None

    for dateiname in os.listdir(verzeichnis):
        if dateiname.endswith('.xml'):
            dateipfad = os.path.join(verzeichnis, dateiname)
            ergebnisse = verarbeite_esl_xml(dateipfad)

            for ergebnis in ergebnisse:
                timestamp = ergebnis["timestamp"]
                monat_jahr_key = timestamp[:7]  # Annahme, dass das Format 'YYYY-MM-DD' ist

                # Frühestes Datum bestimmen
                if earliest_timestamp is None or timestamp < earliest_timestamp:
                    earliest_timestamp = timestamp

                if monat_jahr_key in gesamt_ergebnis_dict:
                    gesamt_ergebnis_dict[monat_jahr_key]["value_bezug"] = max(gesamt_ergebnis_dict[monat_jahr_key]["value_bezug"], ergebnis["value_bezug"])
                    gesamt_ergebnis_dict[monat_jahr_key]["value_geben"] = max(gesamt_ergebnis_dict[monat_jahr_key]["value_geben"], ergebnis["value_geben"])
                else:
                    gesamt_ergebnis_dict[monat_jahr_key] = ergebnis

    sortierte_ergebnisse = sorted(gesamt_ergebnis_dict.values(), key=lambda x: x["timestamp"])
    return sortierte_ergebnisse, earliest_timestamp



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

def kombiniere_esl_sdat(esl_daten, sdat_daten):
    kombinierte_daten = []
    
    # Der zweite Rückgabewert von `verarbeite_esl_verzeichnis` ist unser frühstes Datum
    esl_daten, earliest_timestamp = esl_daten

    # Erstellen eines Dictionaries für leichteren Zugriff auf die ESL Monatsanfänge
    esl_dict = {eintrag['timestamp'][:7]: eintrag for eintrag in esl_daten}
    
    for sdat_eintrag in sdat_daten:
        sdat_datetime = datetime.strptime(sdat_eintrag["timestamp"], "%d.%m.%Y %H:%M")
        monat_key = "{}-{}".format(sdat_eintrag["timestamp"][6:10], sdat_eintrag["timestamp"][3:5])
        basis_eintrag = esl_dict.get(monat_key)

        if basis_eintrag:
            if sdat_datetime >= datetime.fromisoformat(earliest_timestamp):
                # Daten HINZUFÜGEN, die NACH dem ersten ESL Datum liegen
                kombinierte_daten.append({
                    "timestamp": sdat_datetime.isoformat(),
                    "value_bezug": basis_eintrag["value_bezug"] + sdat_eintrag["value_bezug"],
                    "value_geben": basis_eintrag["value_geben"] + sdat_eintrag["value_geben"]
                })
                basis_eintrag["value_bezug"] += sdat_eintrag["value_bezug"]
                basis_eintrag["value_geben"] += sdat_eintrag["value_geben"]
            else:
                # Daten ABZIEHEN, die VOR dem ersten ESL Datum liegen
                kombinierte_daten.append({
                    "timestamp": sdat_datetime.isoformat(),
                    "value_bezug": basis_eintrag["value_bezug"] - sdat_eintrag["value_bezug"],
                    "value_geben": basis_eintrag["value_geben"] - sdat_eintrag["value_geben"]
                })
                basis_eintrag["value_bezug"] -= sdat_eintrag["value_bezug"]
                basis_eintrag["value_geben"] -= sdat_eintrag["value_geben"]

    return kombinierte_daten

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

@app.route('/sdat-esl')
def combined():
    sdat_verzeichnis = request.args.get('sdat')
    esl_verzeichnis = request.args.get('esl')

    sdat_daten = verarbeite_xml_verzeichnis_sdat(sdat_verzeichnis)
    esl_daten = verarbeite_esl_verzeichnis(esl_verzeichnis)

    kombinierte_daten_liste = kombiniere_esl_sdat(esl_daten, sdat_daten)

    return jsonify(kombinierte_daten_liste)


if __name__ == '__main__':
    app.run(debug=True)

