from database import db, Map, Highscore, key_to_column, base_skins
from flask import Blueprint, request, Response, jsonify
from dataclasses import dataclass, field
import json
from collections import defaultdict
from srb2_query import SRB2Query
from config import Config
from fuzzywuzzy import process, fuzz
from werkzeug.exceptions import HTTPException
from sqlalchemy import func

# setup the api section of the site
api_prefix = "/highscores/api"
api_routes = Blueprint('api', __name__)

# class for the api search parameters
@dataclass
class GetParam:
    param: str
    description: str
    values: list = None

# class for the api endpoints
@dataclass
class Endpoint:
    url: str
    description: str
    get_params: list = field(default_factory=list)


# convert a list to json
def to_json(s):
    return json.dumps([x._asdict() for x in s], default=lambda o: str(o))

# get all the users in the database
def get_users():
    users = db.session.query(Highscore.username).distinct().all()
    return [x.username for x in users]

# get all the skins in the database
def get_skins():
    skins = db.session.query(Highscore.skin).distinct().all()
    return [x.skin for x in skins]

# get all the maps in the database
# @param in_rotation: Only return maps that are in rotation
def get_maps(id=None, in_rotation=True):
    query = db.session.query(Map)
    if in_rotation:
        query = query.filter(Map.in_rotation)
    if id:
        query = query.filter(Map.id == id)
        return query.one_or_none()
    return query.all()

# get the best highscores for each skin in each map
def get_map_highscores():
    # get the best time for each map and skin
    best_map = db.session.query(
        db.func.min(Highscore.time).label("time"),
        Highscore.skin,
        Highscore.map_id) \
        .group_by(Highscore.skin,
                  Highscore.map_id).subquery()
    # get all the highscores and select the scores from the found best scores
    query = db.session.query(
        Map.id.label("map_id"),
        Map.name.label("mapname"),
        Highscore.skin,
        Highscore.username,
        Highscore.time,
        Highscore.time_string,
        Highscore.datetime
    ).select_from(Map,
                  db.join(Highscore, best_map,
                          (Highscore.skin == best_map.c.skin) & \
                          (Highscore.map_id == best_map.c.map_id) & \
                          (Highscore.time == best_map.c.time))) \
        .filter(Map.id == Highscore.map_id) \
        .order_by(Map.id, Highscore.time.asc())
    
    maps = {}
    
    # for every score in the filtered scores
    for row in query.all():
        # save the scores
        map = maps.get(row.map_id, {
            'id': row.map_id,
            'name': row.mapname,
            'skins': []
        })
        map['skins'].append({
            'name': row.skin,
            'username': row.username,
            'time': row.time,
            'time_string': row.time_string,
            'datetime': row.datetime
        })
        maps[row.map_id] = map
    return [x for x in maps.values()]

# Gets the best skins or leaderboard of users in the database 
# returns the leaderboard when arg for_leaderboard is true and the best skins when it's false
def get_best_in_data(for_leaderboard, all_skins=False):
    # setup the dictionaries for the storing of the results
    res = {}
    scoring = defaultdict(int)
    
    # setup the weights for the leaderboard(mariokart's scoring system)
    weights = {
        1:15,
        2:12,
        3:10,
        4:8,
        5:7,
        6:6,
        7:5,
        8:4,
        9:3,
        10:2,
        11:1
    }
    
    # for every map in the highscores
    for map in get_maps():
        scores = search(filters=[Highscore.map_id == map.id], limit=11, all_skins=all_skins)
        # if must return the best skins
        if for_leaderboard:
            # for every score in the map's highscores
            for place, score in enumerate(scores):
                # add increase the points in the dictionary by the username
                scoring[score.username] += weights.get(place+1, 0)
        else:
            # save the point in the dictionary by the first score's skin
            scoring[scores[0].skin] += 1
    # sort the dictionary by most points
    for k, v in sorted(scoring.items(), key=lambda x: x[1], reverse=True):
        res[k] = v
    return res

# converter from tics to string
def tics_to_string(time):
    minutes = time//(60*35)
    seconds = time//35%60
    centiseconds = (time%35) * (100//35)
    return f"{minutes}:"+f"{seconds}".zfill(2)+f".{centiseconds}".zfill(2)


# when the route is api/
@api_routes.route('/')
def api():
    # show the docs for every endpoint in the api section
    endpoints = [
        Endpoint(f'{api_prefix}/maps', 'Return all maps'),
        Endpoint(f'{api_prefix}/maps/<id>', 'Return the specified map'),
        Endpoint(f'{api_prefix}/search', 'Return highscores ordered by time ascending', [
            GetParam('username', 'Search by username'),
            GetParam('mapname', 'Search by map name'),
            GetParam('map_id', 'Search by map id'),
            GetParam('skin', 'Search by skin', values=get_skins()),
            GetParam('limit', 'Set the maximal number of records to return'),
            GetParam('order', 'Order by any of the returned columns', values=[x for x in key_to_column.keys()]),
            GetParam('descending', 'Set the order direction to descending'),
            GetParam('all_scores', 'Set to "on" to get all the scores instead of just the best ones'),
            GetParam('all_skins', 'Set to "on" to get all the skins instead of just the vanilla ones')
        ]),
        Endpoint(f'{api_prefix}/highscores', 'Get best scores per map and skin'),
        Endpoint(f'{api_prefix}/skins', 'Get the different skins in the database'),
        Endpoint(f'{api_prefix}/users', 'Get the different users in the database'),
        Endpoint(f'{api_prefix}/leaderboard', 'Get the leaderboard of the best players', [
            GetParam('all_skins', 'Set to "on" to count points for the scores with all the skins instead of just the vanilla ones')
        ]),
        Endpoint(f'{api_prefix}/bestskins', 'Get the best skins by number of best timed tracks without modded skins', [
            GetParam('all_skins', 'Set to "on" to count points for the scores with all the skins instead of just the vanilla ones')
        ]),
        Endpoint(f'{api_prefix}/maphighscores', 'Get the highscores divided by map'),
        Endpoint(f'{api_prefix}/server_info/[<ip_address>]', 'Get info from the SRB2 server, optionally with the given ip_address instead of the default')
        ]
    # return the docs as json
    response = json.dumps({
        'endpoints': endpoints
    }, default=lambda o: o.__dict__)
    resp = Response(response=response, status=200, mimetype="application/json")
    return resp

# when the route is api/maps
@api_routes.route('/maps')
@api_routes.route('/maps/<id>')
def maps(id=None):
    # return the maps as json
    resp = Response(response=str(get_maps(id, in_rotation=False)), status=200, mimetype="application/json")
    return resp

# when the route is api/users
@api_routes.route('/users')
def api_users():
    # return the users as json
    resp = Response(response=json.dumps(get_users()), status=200, mimetype="application/json")
    return resp

# when the route is api/skins
@api_routes.route('/skins')
def api_skins():
    # return the skins as json
    resp = Response(response=json.dumps(get_skins()), status=200, mimetype="application/json")
    return resp

# when the route is api/leaderboard
@api_routes.route('/leaderboard')
def api_leaderboard():
    # request the params for the skins to be counted
    all_skins = request.args.get("all_skins") == "on"
    
    # return the leaderboard as json
    resp = Response(response=json.dumps(get_best_in_data(True, all_skins)), status=200, mimetype="application/json")
    return resp

# when the route is api/bestskins
@api_routes.route('/bestskins')
def api_best_skins():
    # request the params for the skins to be counted
    all_skins = request.args.get("all_skins") == "on"
    
    # return the best skins as json
    resp = Response(response=json.dumps(get_best_in_data(False, all_skins)), status=200, mimetype="application/json")
    return resp

# when the route is api/maphighscores
@api_routes.route('/maphighscores')
def api_highscores():
    # return the highscores for each skin in each map as json
    resp = Response(response=json.dumps(get_map_highscores(), default=lambda o: str(o)), status=200, mimetype="application/json")
    return resp

def search(filters=[], ordering=None, limit=None, all_skins=False, all_scores=False):
    if not limit:
        limit = 1000
    # subquery to get the best time for each combination (User, Skin, Map)
    best_scores = db.session.query(db.func.min(Highscore.time).label("time"),
                             Highscore.username,
                             Highscore.skin,
                             Highscore.map_id) \
                             .group_by(Highscore.username, 
                                       Highscore.skin, 
                                       Highscore.map_id).subquery()
    
    # get the highscores NOT ORDERED
    query = db.session.query(
        Highscore.username,
        Map.name.label("mapname"),
        Map.id.label("map_id"),
        Highscore.skin,
        Highscore.time,
        Highscore.time_string,
        Highscore.datetime)

    if not all_scores:
        query = query.select_from(Map, db.join(Highscore, best_scores,
                                  (Highscore.username == best_scores.c.username) & \
                                  (Highscore.skin == best_scores.c.skin) & \
                                  (Highscore.map_id == best_scores.c.map_id) & \
                                  (Highscore.time == best_scores.c.time)))

    if not all_skins:
        query = query.filter(Highscore.skin.in_(base_skins))

    query = query.filter(Map.id == Highscore.map_id)

    if ordering is not None:
        query = query.order_by(ordering)

    for filter in filters:
        query = query.filter(filter)

    query = query.order_by(Highscore.time.asc())

    query = query.limit(limit)

    return query.all()
    

# when the route is api/search
@api_routes.route('/search')
def api_search():
    # request the params for the type of scores
    all_scores = request.args.get("all_scores") == "on"
    # request the params for the skins filtering the scores
    all_skins = request.args.get("all_skins") == "on"
    # request the params for the ordering
    order = request.args.get('order')
    descending = 'descending' in request.args

    ordering = None
    # if the order param is valid
    if order in key_to_column:
        # order by the order parameter
        order_by = key_to_column[order]
        # if the descending parameter got passed
        if descending:
            # order in descending order
            order_by = order_by.desc()
        ordering = order_by

    filters=[]
    # for every given parameter
    for key in request.args:
        # if the parameter's key is in the highscores columns
        if key in key_to_column:
            fuzzy_columns = {'username':get_users, 'mapname':lambda:[map.name for map in get_maps(in_rotation=False)], 'skin':get_skins}
            # if the column has to be searched through fuzzywuzzy
            try:
                extracted = process.extractOne(request.args.get(key), fuzzy_columns[key](), scorer=fuzz.ratio)
                filters.append(key_to_column[key] == extracted[0])
            except KeyError:
                # filter the highscores by such column
                filters.append(key_to_column[key] == request.args.get(key))

    limit = request.args.get('limit',None)
    if limit:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            return jsonify(error="Invalid limit"), 400

    scores = search(all_scores=all_scores, all_skins=all_skins, filters=filters, ordering=ordering, limit=limit)
    # return the query as json
    resp = Response(response=to_json(scores), status=200, mimetype="application/json")
    return resp

def get_server_info(ip=Config.srb2_server):
    q = SRB2Query(ip)
    serverpkt, playerpkt = q.askinfo()
    serverinfo = {}
    serverinfo['servername'] = serverpkt.servername
    serverinfo['version'] = serverpkt.version
    serverinfo['number_of_players'] = serverpkt.numberofplayer
    serverinfo['max_players'] = serverpkt.maxplayer
    serverinfo['leveltime'] = serverpkt.leveltime
    serverinfo['leveltime_string'] = tics_to_string(serverpkt.leveltime)
    serverinfo['map'] = {
        'id': serverpkt.map['num'],
        'name': serverpkt.map['title'],
    }
    # Retrieve more map info if it is a known map
    servermap = get_maps(serverpkt.map['num']-1)
    if servermap:
        serverinfo['map'] = servermap.get_dict()
    serverinfo['players'] = []
    for player in playerpkt.players:
        player.pop("address")
        serverinfo['players'].append(player)
    return serverinfo

@api_routes.route('/server_info', defaults={'ip_address': Config.srb2_server})
@api_routes.route('/server_info/<ip_address>')
def server_info(ip_address):
    response = json.dumps(
        get_server_info(ip_address),
        default=lambda x: str(x))
    resp = Response(response=response, status=200, mimetype="application/json")
    return resp

@api_routes.errorhandler(Exception)
def handle_exception(e):
    code = 500
    if isinstance(e, HTTPException):
        code = e.code
    return jsonify(error=str(e)), code
