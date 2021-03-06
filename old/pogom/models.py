#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
from peewee import Model, SqliteDatabase, InsertQuery, IntegerField,\
                   CharField, FloatField, BooleanField, DateTimeField, MySQLDatabase
from datetime import datetime
from base64 import b64encode

from pymysql import OperationalError
from .utils import get_pokemon_name
from .transform import transform_from_wgs_to_gcj
from . import config

# db = SqliteDatabase('pogom.db')
db = MySQLDatabase('pogom', user='pokehunter', password='zhangdamao131330', host='104.236.229.63')
log = logging.getLogger(__name__)


class BaseModel(Model):
    class Meta:
        database = db

    @classmethod
    def get_all(cls):
        return [m for m in cls.select().dicts()]


class Pokemon(BaseModel):
    # We are base64 encoding the ids delivered by the api
    # because they are too big for sqlite to handle
    encounter_id = CharField(primary_key=True)
    spawnpoint_id = CharField()
    pokemon_id = IntegerField()
    latitude = FloatField()
    longitude = FloatField()
    disappear_time = DateTimeField()

    @classmethod
    def get_active(cls):
        query = (Pokemon
                 .select()
                 .where(Pokemon.disappear_time > datetime.utcnow())
                 .dicts())

        pokemons = []
        for p in query:
            p['pokemon_name'] = get_pokemon_name(p['pokemon_id'])
            pokemons.append(p)

        return pokemons


class Pokestop(BaseModel):
    pokestop_id = CharField(primary_key=True)
    enabled = BooleanField()
    latitude = FloatField()
    longitude = FloatField()
    last_modified = DateTimeField()
    lure_expiration = DateTimeField(null=True)
    active_pokemon_id = IntegerField(null=True)


class Gym(BaseModel):
    UNCONTESTED = 0
    TEAM_MYSTIC = 1
    TEAM_VALOR = 2
    TEAM_INSTINCT = 3

    gym_id = CharField(primary_key=True)
    team_id = IntegerField()
    guard_pokemon_id = IntegerField()
    gym_points = IntegerField()
    enabled = BooleanField()
    latitude = FloatField()
    longitude = FloatField()
    last_modified = DateTimeField()


def parse_map(map_dict, step):
    pokemons = {}
    pokestops = {}
    gyms = {}

    cells = map_dict['responses']['GET_MAP_OBJECTS']['map_cells']
    for cell in cells:
        # for p in cell.get('wild_pokemons', []):
        #
        #     pokemons[p['encounter_id']] = {
        #         'encounter_id': b64encode(str(p['encounter_id'])),
        #         'spawnpoint_id': p['spawnpoint_id'],
        #         'pokemon_id': p['pokemon_data']['pokemon_id'],
        #         'latitude': p['latitude'],
        #         'longitude': p['longitude'],
        #         'disappear_time': datetime.utcfromtimestamp(
        #             (p['last_modified_timestamp_ms'] +
        #              p['time_till_hidden_ms']) / 1000.0)
        #     }

        for f in cell.get('forts', []):
            if f.get('type') == 1:  # Pokestops
                    if 'lure_info' in f:
                        lure_expiration = datetime.utcfromtimestamp(
                            f['lure_info']['lure_expires_timestamp_ms'] / 1000.0)
                        active_pokemon_id = f['lure_info']['active_pokemon_id']
                    else:
                        lure_expiration, active_pokemon_id = None, None

                    pokestops[f['id']] = {
                        'pokestop_id': f['id'],
                        'enabled': f['enabled'],
                        'latitude': f['latitude'],
                        'longitude': f['longitude'],
                        'last_modified': datetime.utcfromtimestamp(
                            f['last_modified_timestamp_ms'] / 1000.0),
                        'lure_expiration': lure_expiration,
                        'active_pokemon_id': active_pokemon_id
                }

            else:  # Currently, there are only stops and gyms
                gyms[f['id']] = {
                    'gym_id': f['id'],
                    'team_id': f['owned_by_team'],
                    'guard_pokemon_id': f['guard_pokemon_id'],
                    'gym_points': f['gym_points'],
                    'enabled': f['enabled'],
                    'latitude': f['latitude'],
                    'longitude': f['longitude'],
                    'last_modified': datetime.utcfromtimestamp(
                        f['last_modified_timestamp_ms'] / 1000.0),
                }

    if pokemons:
        log.info("Upserting {} pokemon".format(len(pokemons)))
        bulk_upsert(Pokemon, pokemons, step)

    if pokestops:
        log.info("Upserting {} pokestops".format(len(pokestops)))
        bulk_upsert(Pokestop, pokestops, step)

    if gyms:
        log.info("Upserting {} gyms".format(len(gyms)))
        bulk_upsert(Gym, gyms, step)

def bulk_upsert(cls, data, cstep):
    num_rows = len(data.values())
    i = 0
    step = 120
    success = False
    while i < num_rows:
        log.debug("Inserting items {} to {}".format(i, min(i+step, num_rows)))
        try:
            success = InsertQuery(cls, rows=data.values()[i:min(i+step, num_rows)]).upsert().execute()
        except:
            db.connect()
            success = InsertQuery(cls, rows=data.values()[i:min(i+step, num_rows)]).upsert().execute()
        i+=step
    if cstep > config['LAST_RECORD_STEP'] and success:
        config['LAST_RECORD_STEP'] = cstep
        target = open(config['LOG_FILE'], 'r')
        num = int(target.read())
        if config['LOG_FILE'] != '' and num < cstep:
            target = open(config['LOG_FILE'], 'w')
            target.write(str(config['LAST_RECORD_STEP']))
            target.close()


def create_tables():
    db.connect()
    db.create_tables([Pokemon, Pokestop, Gym], safe=True)
    db.close()
