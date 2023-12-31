from flask import Flask, request, jsonify
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from flask_cors import CORS
import zipfile
import os
import shutil


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
    start_time = datetime.fromisoformat(start_time_str.replace("Z", ""))
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
        formatted_timestamp = timestamp.isoformat()

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

    gesamt_ergebnis_liste = list(gesamt_ergebnis_dict.values())
    gesamt_ergebnis_liste.sort(key=lambda x: datetime.fromisoformat(x["timestamp"]))

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
        sdat_datetime = datetime.fromisoformat(sdat_eintrag["timestamp"])
        monat_key = sdat_datetime.strftime('%Y-%m')

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

def handle_upload(file, target_folder):
    """Hilfsfunktion, um die Datei-Upload-Logik zu kapseln."""
    if file and file.filename.endswith('.zip'):
        zip_path = os.path.join(".", file.filename)  # Speichern im aktuellen Verzeichnis
        file.save(zip_path)
        
        # Entpacken der ZIP-Datei
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Zuerst alle XML-Dateien in das Zielverzeichnis extrahieren
            for member in zip_ref.namelist():
                if member.endswith('.xml'):
                    zip_ref.extract(member, target_folder)
                    
                    
        return "Dateien erfolgreich entpackt und gespeichert.", 200

    return "Ungültige Datei.", 400

def get_first_subfolder(main_folder):
    """Ermittelt den ersten Unterordner eines gegebenen Hauptordners."""
    try:
        subfolders = [f.path for f in os.scandir(main_folder) if f.is_dir()]
        return subfolders[0] if subfolders else None
    except Exception as e:
        print(f"Fehler beim Abrufen des Unterordners: {e}")
        return None

@app.route('/')
def hello_world():
    with open('index.html', 'r') as file:
        return file.read()

@app.route('/upload_zip_sdat', methods=['POST'])
def upload_zip_sdat():
    return handle_upload(request.files['file'], "./sdat_xml_dateien/")

@app.route('/upload_zip_esl', methods=['POST'])
def upload_zip_esl():
    return handle_upload(request.files['file'], "./esl_xml_dateien/")

@app.route('/upload', methods=['POST'])
def upload():
    sdat_response = handle_upload(request.files['sdat'], "./sdat_xml_dateien/")
    esl_response = handle_upload(request.files['esl'], "./esl_xml_dateien/")
    
    # Hier könnten Sie die Antworten kombinieren oder eine Auswahl treffen.
    return jsonify({"sdat": sdat_response, "esl": esl_response})

@app.route('/sdat')
def sdat():
    subfolder_path = get_first_subfolder('sdat_xml_dateien')
    if not subfolder_path:
        return "Fehler beim Abrufen der XML-Dateien.", 500
    return verarbeite_xml_verzeichnis_sdat(subfolder_path)

@app.route('/esl')
def esl():
    subfolder_path = get_first_subfolder('esl_xml_dateien')
    if not subfolder_path:
        return jsonify({"error": "Fehler beim Abrufen der XML-Dateien."}), 500
    print(subfolder_path)
    return jsonify(verarbeite_esl_verzeichnis(subfolder_path))

@app.route('/sdat-esl')
def combined():
    sdat_verzeichnis = request.args.get('sdat')
    esl_verzeichnis = request.args.get('esl')

    sdat_daten = verarbeite_xml_verzeichnis_sdat('sdat_xml_dateien')
    esl_daten = verarbeite_esl_verzeichnis('esl_xml_dateien')

    kombinierte_daten_liste = kombiniere_esl_sdat(esl_daten, sdat_daten)

    return jsonify(kombinierte_daten_liste)

if __name__ == '__main__':
    for folder in ["./sdat_xml_dateien/", "./esl_xml_dateien/"]:
        if not os.path.exists(folder):
            os.makedirs(folder)
    app.run(debug=True)

