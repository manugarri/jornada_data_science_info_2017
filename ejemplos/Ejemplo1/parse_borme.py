#! /usr/bin/env python
"""
Herramienta para descargarse datos historicos del Boletin Oficial del Registro Mercantil.

Para usar:
>> python parse_borme.py INICIO_FECHA FIN_FECHA REGIONES OUTPUT
con:
- INICIO_FECHA es la fecha de inicio que se desea procesar, en formato %Y-%m-%d
- FIN_FECHA es la fecha final que se desea procesar, en formato %Y-%m-%d
- REGIONES son una lista de regiones separadas por coma que se desean, por ejemplo MURCIA,MADRID,BARCELONA
- OUTPUT es el nombre del archivo donde guardar los resultados

requisitos:
    python-tika
    python-fire
    numpy (se puede eliminar cambiando la funcion para generar el rango de fechas)
    requests
    xmltodict

Como funciona:
1) Se conecta a la pagina con los resumenes diarios del BORME, tiene el formato http://boe.es/diario_borme/xml.php?id=BORME-S-20170301
2) Obtiene los links de los registros de las regiones seleccionadas en pdf, por ejemplo 
3) Por cada link
  3.1) Se lo descarga
  3.2) Extrae el texto de todos los registros
  3.3) Extrae la informacion según la acción que representa, las acciones válidas se definen en AVAILABLE_ACTIONS
4) Escribe los registros en el archivo output
"""

import asyncio
import json
import re
from datetime import datetime

import fire
import numpy as np
import psutil
from tika.tika import parse1
import requests
import xmltodict

__author__ = "manugarri"

BORME_SUMMARY_URL = "http://boe.es/diario_borme/xml.php?id=BORME-S-{date}"
AVAILABLE_ACTIONS = [
        'Ampliación del objeto social.',
        'Ampliacion del objeto social',
        'Ampliación de capital.',
        'Cambio de denominación social.',
        'Cambio de domicilio social.',
        'Cambio de identidad del socio único:',
        'Cambio de objeto social.',
        'Cancelaciones de oficio de nombramientos.',
        'Ceses/Dimisiones.',
        'Cierre provisional hoja registral',
        'Constitución.',
        'Datos registrales.',
        'Declaración de unipersonalidad.',
        'Disolución.',
        'Extinción.',
        'Fe de erratas:',
        'Fusión por absorción.',
        'Justificacion de no aprobacion de cuentas del ejercicio',
        'Modificaciones estatutarias.',
        'Nombramientos.',
        'Otros conceptos.',
        'Pérdida del caracter de unipersonalidad.',
        'Reapertura hoja registral.',
        'Reducción de capital.',
        'Reelecciones.',
        'Revocaciones.',
        'Segregación.',
        'Situación concursal.',
        'Transformación de sociedad.',
        ]

def get_date_summary(date):
    formatted_date = date.strftime("%Y%m%d")
    summary_xml = requests.get(BORME_SUMMARY_URL.format(date=formatted_date)).content
    return xmltodict.parse(summary_xml)

def get_date_bulletins(date):
    summary = get_date_summary(date)
    region_bulletin_links = {}
    if 'error' in summary.keys():
        print('Error on date {}:\n{}\n'.format(date, summary['error']))
        return None

    daily_summary = summary['sumario']['diario']
    if isinstance(daily_summary, dict):
        region_items = daily_summary['seccion'][0]['emisor']['item']
    elif isinstance(daily_summary, list):
        region_items = [s.get('emisor') for s in daily_summary[1]['seccion']][0]['item']

    for item in region_items:
        region_bulletin_links[item['titulo']] = "http://boe.es" + item['urlPdf']['#text']
    return region_bulletin_links

def kill_tika_server():
    for proc in psutil.process_iter():
        if proc.name()=='java' and 'tika' in ' '.join(proc.cmdline()):
            print("Killing Process: ", proc)
            proc.kill()

def parse_entry_text(entry_text):
    entry_action_indexes = []
    title, body = entry_text.split('\n', maxsplit=1)
    for action in AVAILABLE_ACTIONS:
        action_search = re.search(action, body)
        if action_search:
            entry_action_indexes.append(action_search.span())
    entry_action_indexes = sorted(entry_action_indexes, key=lambda x: x[0])
    entry_data = {"title": title, "actions":[]}
    for i in range(len(entry_action_indexes)):
        cur_action = entry_action_indexes[i]
        action = body[cur_action[0]: cur_action[1]]
        try:
            description = body[cur_action[1]:entry_action_indexes[i+1][0]]
        except IndexError:
            description = body[cur_action[1]:len(body)]
        entry_data["actions"].append({
            "action_type":action,
            "action_description": description
            })
    return entry_data

@asyncio.coroutine
def process_bulletin(bulletin_link, date_str, region, output_fname):
    def parse_pdf(pdf_link):
        jsonOutput = parse1("text", bulletin_link)
        if jsonOutput[0] != 200:
            print("Error with pdf url {}".format(bulletin_link))
            return []
        text = jsonOutput[1].encode('utf-8').decode()
        text_entries = [line for line in text.split('\n\n') if re.match('^\s*[0-9]+ - ',line)]
        return text_entries
    try:
        bulletin_text = parse_pdf(bulletin_link)
        bulletin_data = []
        for entry_text in bulletin_text:
            entry_data = parse_entry_text(entry_text)
            entry_data['date'] = date_str
            entry_data['region'] = region
            entry_data['raw'] = entry_text
            bulletin_data.append(entry_data)
        save_bulletin_data(bulletin_data, output_fname)
    except Exception as e:
        print("ERROR in date {}\n{}".format(date_str, e))

def save_bulletin_data(bulletin_data, fname):
    with open(fname, 'a') as f:
        for entry in bulletin_data:
            entry_str = json.dumps(entry, ensure_ascii=False)
            f.write(entry_str)
            f.write('\n')

def parse_date_fillings(date, regions=None, output_fname=None):
    date_str = date.strftime('%Y-%m-%d')
    if not output_fname:
        output_fname = 'borme_entries_{}'.format(date_str)
    date_bulletins = get_date_bulletins(date)

    if not date_bulletins:
        print('No valid links for date {}'.format(date))
        return
    if not regions:
        regions = date_bulletins.keys()
    elif not set(regions).intersection(set(date_bulletins.keys())):
        print("No bulletins for regions {} in date {}".format(regions, date))
        return

    loop = asyncio.get_event_loop()
    tasks = [
            asyncio.async(process_bulletin(date_bulletins[r], date_str, r, output_fname)) for r in regions
            ]
    loop.run_until_complete(asyncio.wait(tasks, timeout=5))

def get_range_fillings(start, end, regions_str=None, output=None):
    if not regions_str:
        regions = None
    else:
        regions = regions_str.split(',')
    date_start = datetime.strptime(start, '%Y-%m-%d').date()
    date_end = datetime.strptime(end, '%Y-%m-%d').date()
    date_range = np.arange(np.datetime64(date_start), np.datetime64(date_end)).astype(datetime)
    for date in date_range:
        print("Processing date {}".format(date))
        try:
            parse_date_fillings(date, regions=regions, output_fname=output)
        except Exception as e:
            print("Error parsing the date {}".format(date))

if __name__ == '__main__':
    fire.Fire()
    kill_tika_server()
