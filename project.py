"""Imports"""
from flask import Flask, render_template, request, redirect, jsonify, url_for
from flask import flash
from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker
from database_setup import Base, Team, Player, User
from flask import session as login_session
import random
import string
import httplib2
import json
from flask import make_response
import requests
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError

"""Flask instance"""
app = Flask(__name__)

"""GConnect CLIENT_ID"""
CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "FIFA World Cup"


# Connect to Database and create database session
engine = create_engine('sqlite:///fifaworldcup.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(
        random.choice(
            string.ascii_uppercase +
            string.digits) for x in range(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code, now compatible with Python3
    # request.get_data()
    code = request.data.decode('utf-8')

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    # Submit request, parse response - Python3 compatible
    h = httplib2.Http()
    response = h.request(url, 'GET')[1]
    str_response = response.decode('utf-8')
    result = json.loads(str_response)

    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px; \
    border-radius: 150px;-webkit-border-radius: 150px; \
    -moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    return output

# User Helper Functions


def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
                   'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except BaseException:
        return None

# DISCONNECT - Revoke a current user's token and reset their login_session


@app.route('/gdisconnect')
def gdisconnect():
        # Only disconnect a connected user.
    access_token = login_session.get('access_token')
    if access_token is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] == '200':
        # Reset the user's sesson.
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']

        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        # For whatever reason, the given token was invalid.
        response = make_response(
            json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response


# JSON APIs to view Team Information
@app.route('/team/<int:team_id>/player/JSON')
def restaurantMenuJSON(team_id):
    team = session.query(Team).filter_by(id=team_id).one()
    items = session.query(Player).filter_by(
        team_id=team_id).all()
    return jsonify(Players=[i.serialize for i in items])


@app.route('/team/<int:team_id>/player/<int:player_id>/JSON')
def menuItemJSON(team_id, player_id):
    Player = session.query(Player).filter_by(id=player_id).one()
    return jsonify(Player=Player.serialize)


@app.route('/team/JSON')
def restaurantsJSON():
    teams = session.query(Team).all()
    return jsonify(teams=[r.serialize for r in teams])


# Show all teams
@app.route('/')
@app.route('/team/')
def showTeams():
    """Renders html page to show teams"""
    teams = session.query(Team).order_by(asc(Team.name))
    if 'username' not in login_session:
        return render_template('publicteams.html', teams=teams)
    else:
        return render_template('teams.html', teams=teams)

# Create a new team


@app.route('/team/new/', methods=['GET', 'POST'])
def newTeam():
    """Renders html page for creating new team in db"""
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newTeam = Team(
            name=request.form['name'], user_id=login_session['user_id'])
        session.add(newTeam)
        flash('New Team %s Successfully Created' % newTeam.name)
        session.commit()
        return redirect(url_for('showTeams'))
    else:
        return render_template('newTeam.html')

# Edit a team


@app.route('/team/<int:team_id>/edit/', methods=['GET', 'POST'])
def editTeam(team_id):
    """Edit team and have new value stored in db and rendered in html page"""
    editedRestaurant = session.query(
        Team).filter_by(id=team_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if editedRestaurant.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not \
        authorized to edit this team. Please create your own team in \
        order to edit.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        if request.form['name']:
            editedRestaurant.name = request.form['name']
            flash('Team Successfully Edited %s' % editedRestaurant.name)
            return redirect(url_for('showTeams'))
    else:
        return render_template('editTeam.html', team=editedRestaurant)


# Delete a team
@app.route('/team/<int:team_id>/delete/', methods=['GET', 'POST'])
def deleteTeam(team_id):
    """Delete team from db and render html page with updated db"""
    restaurantToDelete = session.query(
        Team).filter_by(id=team_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if restaurantToDelete.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert('You are not \
        authorized to delete this team. Please create your own team in \
        order to delete.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        session.delete(restaurantToDelete)
        flash('%s Successfully Deleted' % restaurantToDelete.name)
        session.commit()
        return redirect(url_for('showTeams', team_id=team_id))
    else:
        return render_template('deleteTeam.html', team=restaurantToDelete)

# Show team and players


@app.route('/team/<int:team_id>/')
@app.route('/team/<int:team_id>/player/')
def showPlayer(team_id):
    """Renders html page to show player"""
    team = session.query(Team).filter_by(id=team_id).one()
    creator = getUserInfo(team.user_id)
    items = session.query(Player).filter_by(
        team_id=team_id).all()
    if 'username' not in login_session or \
       creator.id != login_session['user_id']:
        return render_template(
            'publicplayer.html',
            items=items,
            team=team,
            creator=creator)
    else:
        return render_template(
            'player.html',
            items=items,
            team=team,
            creator=creator)


# Add a new player
@app.route('/team/<int:team_id>/player/new/', methods=['GET', 'POST'])
def newPlayer(team_id):
    """ Renders html page for creating new player in db """
    if 'username' not in login_session:
        return redirect('/login')
    team = session.query(Team).filter_by(id=team_id).one()
    if login_session['user_id'] != team.user_id:
        return "<script>function myFunction() {alert('You are not authorized \
        to add players to this team. Please create your own team in order to \
        add players.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        newItem = Player(
            name=request.form['name'],
            description=request.form['description'],
            team_id=team_id,
            user_id=team.user_id
        )
        session.add(newItem)
        session.commit()
        flash('New Player %s Successfully Created' % (newItem.name))
        return redirect(url_for('showPlayer', team_id=team_id))
    else:
        return render_template('newplayer.html', team_id=team_id)

# Edit a menu item


@app.route(
    '/team/<int:team_id>/player/<int:player_id>/edit',
    methods=[
        'GET',
        'POST'])
def editPlayer(team_id, player_id):
    """Edit player and have new value stored in db and rendered in html page"""
    if 'username' not in login_session:
        return redirect('/login')
    editedItem = session.query(Player).filter_by(id=player_id).one()
    team = session.query(Team).filter_by(id=team_id).one()
    if login_session['user_id'] != team.user_id:
        return "<script>function myFunction() {alert('You are not authorized \
        to edit players for this team. Please create your own team in order \
        to edit players.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        session.add(editedItem)
        session.commit()
        flash('Player Successfully Edited')
        return redirect(url_for('showPlayer', team_id=team_id))
    else:
        return render_template(
            'editplayer.html',
            team_id=team_id,
            player_id=player_id,
            item=editedItem)


# Delete a menu item
@app.route(
    '/team/<int:team_id>/player/<int:player_id>/delete',
    methods=[
        'GET',
        'POST'])
def deletePlayer(team_id, player_id):
    """Delete player from db and render html page with updated db"""
    if 'username' not in login_session:
        return redirect('/login')
    team = session.query(Team).filter_by(id=team_id).one()
    itemToDelete = session.query(Player).filter_by(id=player_id).one()
    if login_session['user_id'] != team.user_id:
        return "<script>function myFunction() {alert('You are not authorized \
        to delete menu items to this team. Please create your own team in \
        order to delete items.');}</script><body onload='myFunction()''>"
    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        flash('Player Successfully Deleted')
        return redirect(url_for('showPlayer', team_id=team_id))
    else:
        return render_template('deletePlayer.html', item=itemToDelete)


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000, threaded=False)
