import sys
import json
import requests
import pandas as pd
import numpy as np
import os.path
import datetime
import sqlite3
import hashlib
from pandas import HDFStore
import plotly
import collectobot

DATA_PATH = '../test_data/' #TODO in current directory while testing, needs to be fixed before shipping!
HDF_NAME = '../test_data/cbot.hdf5'
GRAPH_DATABASE = '../test_data/graph.db'

class yaha_analyzer(object):

    def __init__(self):
        self.total_pages = 0
        self.history = []
        self.username = ''
        self.api_key = ''
        self.new_data = False

    def generate_collectobot_data(self):
        """
        Generates collect-o-bot data from the database, writes it to a hdf5 file
        """
        results = collectobot.aggregate()
        self.games = results
        self.history = {'children': results, 'meta': {'total_items': len(results)}}
        self.generate_decks(dates = False)
        self.write_hdf5(HDF_NAME)
        return results


    def open_collectobot_data(self):
        """
        Loads the collectobot data from a hdf5 file
        """
        self.read_data(hdf5_name=HDF_NAME)

    def _load_json_data(self, json_file):
        """
        Opens a json file and loads it into the object, this method is meant for testing

        Keyword parameter:
        json_file -- str, location of the json file
        """
        with open(json_file, "r") as infile:
            results = json.load(infile)
        self.history = results
        self.generate_decks()
        return results

    def pull_data(self, username, api_key):
        """

        Grabs the data from the trackobot servers, writes it out to a new files and the database if it doesn't exist/outdated

        Keyword parameters:
        username -- str, trackobot username
        api_key -- str, trackobot api_key

        Returns:
        The contents of the json_file (includes history & metadata)
        """
        self.username = username
        self.api_key = api_key
        url = 'https://trackobot.com/profile/history.json?'
        auth = {'username': username, 'token': api_key}
        req = requests.get(url, params=auth).json()
        metadata = req['meta']
        user_hash, count, json_name, hdf5_name = self.store_data()
        #if it's not equal, repull
        if metadata['total_items'] != count or not self.check_data(json_name, hdf5_name):
            results = {'children': req['history']}
            if metadata['total_pages'] != None:
                for page_number in range(2, metadata['total_pages']+1):
                    auth['page'] = page_number
                    results['children'].extend(requests.get(url, params=auth).json()['history'])
            results['meta'] = {'total_items': metadata['total_items']}
            self.history = results
            self.generate_decks()
            self.write_hdf5(hdf5_name)
            with open('{}{}'.format(DATA_PATH, json_name), "w") as outfile:
                json.dump(results, outfile)
            self.update_count(user_hash, metadata['total_items']) #once everything's been loaded and written, update the total_items count in the database
        else:
            results = self.read_data(json_name, hdf5_name)
        return results

    def generate_decks(self, dates = True):
        """
        Differentiates between the different deck types, and sorts them into their individual lists (history is a massive array, transform into a pandas dataframe for processing)

        Returns:
        Pandas dataframe with all the games
        """
        self.games = pd.DataFrame(self.history['children'])
        self.games.loc[self.games['hero_deck'].isnull(), 'hero_deck'] = 'Other'
        self.games.loc[self.games['opponent_deck'].isnull(), 'opponent_deck'] = 'Other'
        self.games['p_deck_type'] = self.games['hero_deck'].map(str) + '_' +  self.games['hero']
        self.games['o_deck_type'] = self.games['opponent_deck'].map(str) + '_' + self.games['opponent']

        self._generate_cards_played()
        if dates:
            self._make_dates()
        self.games = self.games[self.games['card_history'].str.len() != 0]
        return self.games

    def _unique_decks(self, game_mode='ranked', game_threshold = 5, formatted = True):
        """
        Returns a list with the unique decks for that game mode in self.games
        >> Don't actually use this, call the database instead

        Keyword parameters:
        game_mode -- str, the game mode, 'ranked', 'casual', or 'both'
        game_threshold -- int, the minimum amount of games the deck has to show up

        Returns:
        A list of unique p_deck_types
        """
        deck_types = self.generate_matchups(game_mode, game_threshold).reset_index()
        deck_types = deck_types['p_deck_type'].unique()
        if formatted:
            return sorted(list(map(lambda x: x.replace("_", " "), deck_types)))
        return deck_types

    def _unique_cards(self, game_mode='ranked', game_threshold = 5, formatted = True):
        """
        Returns a list with the unique cards for that game mode in self.games
        >> Don't actually use this, call the database instead

        Keyword parameters:
        game_mode -- str, the game mode, 'ranked', 'casual', or 'both'
        game_threshold -- int, the minimum amount of games the deck has to show up

        Returns:
        A list of unique card names
        """
        cards = self.generate_card_stats(game_mode, game_threshold).reset_index()
        cards = cards['card'].unique().tolist()
        return cards

    def _make_dates(self):
        """Internal method -- Converts the dates in self.games to separate columns for easier parsing, called by generate_decks"""
        format_date = lambda x: datetime.datetime.strptime(x, '%Y-%m-%dT%H:%M:%S.%fZ')
        split_date = lambda x: {'year': x.year, 'month': x.month, 'day': x.day, 'hour': x.hour, 'minute': x.minute, 'second': x.second}
        date_df = pd.DataFrame(list(map(lambda x: split_date(format_date(x)), self.games['added'])))
        self.games = self.games.join(date_df, how='outer')

    def _get_card_list(self, dict_list, player='me'):
        """
        Internal method -- Returns the list of cards that were played in a game, called by _generate_cards_played

        Keyword parameters:
        dict_list -- list of dictionaries from the ['card_history'] column in self.games for one particular game
        player -- the player to be parsing

        Returns:
        p_card_list -- array of card names (str)
        """
        p_card_list = list(filter(None, map(lambda x: x['card']['name'] if x['player'] == player else None, dict_list)))
        return p_card_list


    def _generate_cards_played(self):
        """Internal method -- Generates a list of cards for player and opponent into the list ['p_cards_played'] and ['o_cards_played'], called by generate_decks"""
        self.games['p_cards_played'] = self.games['card_history'].map(lambda x: self._get_card_list(x, player='me'))
        self.games['o_cards_played'] = self.games['card_history'].map(lambda x: self._get_card_list(x, player='opponent'))

    def generate_matchups(self, game_mode = 'ranked', game_threshold = 0):
        """
        Generates a pandas groupby table with duration, count, coin, win #, win%, and card_history

        Keyword parameter:
        game_mode -- str, either 'ranked', 'casual', or 'both', default is ranked
        game_threshold -- lowerbound for games played, any # of games lower than the threshold are not returned

        Returns:
        grouped -- pandas groupby object, indicies are player deck 'p_deck_type' then opponent 'o_deck_type'
        """
        decks = self.games
        if game_mode != 'both':
            decks = decks[decks['mode'] == game_mode]
        decks.loc[:, 'win'] = decks['result'].map(lambda x: True if x == 'win' else False)
        decks.loc[:, 'count'] = [1]*len(decks)

        grouped = decks.groupby(['p_deck_type', 'o_deck_type']).agg({'coin': np.sum, 'duration': [np.mean, np.std], 'count': np.sum, 'win': np.sum, 'card_history': lambda x: tuple(x)})
        grouped['win%'] = grouped['win']['sum']/grouped['count']['sum']*100
        grouped = grouped[grouped['count']['sum'] > game_threshold]
        return grouped #note this returns a groupby, so a reset_index is necessary before pivoting/plotting


    def create_matchup_heatmap(self, game_mode = 'ranked', game_threshold = 0):
        """
        Returns a list of one dictionary to be used with plotly's json render

        Keyword parameter:
        game_mode -- str, either 'ranked', 'casual', or 'both', default is ranked
        game_threshold -- lowerbound for games played, any # of games lower than the threshold are not returned

        Returns:
        graphs -- a list of one dictionary to be used with plotly.utils.PlotlyJSONEncoder
        """
        data = self.generate_matchups(game_mode, game_threshold).reset_index()
        data = data[['p_deck_type', 'o_deck_type', 'win%']]
        x_vals = data['o_deck_type'].map(lambda x: x.replace('_', ' '))
        y_vals = data['p_deck_type'].map(lambda x: x.replace('_', ' '))
        data = data.pivot('o_deck_type', 'p_deck_type')

        graphs = [
            dict(
                data=[
                    dict(
                        z = [data[x].values.tolist() for x in data.columns],
                        y = y_vals,
                        x = x_vals,
                        type='heatmap',
                        colorscale='Viridis'

                )
                ],
                layout = dict(
                    margin = dict(
                        l = 160,
                        b = 160
                    ),
                    height = 900
                )
            )
        ]

        return graphs

    def generate_cards(self, filtered):
        """
        Generates a grouped win/loss count for specific cards

        Keyword parameter:
        filtered -- pandas dataframe, should be a subset of self.games filtered somehow

        Returns:
        p_df -- pandas groupby object, cards marked as 'me' for player, index is the card name ['card'], columns are win count and loss count ['win', 'loss']
        o_df -- pandas groupby object, cards marked as 'opponent' for player, index is the card name ['card'], columns are win count and loss count ['win', 'loss']
        """
        p_df = []
        o_df = []
        for r in zip(filtered['p_cards_played'], filtered['o_cards_played'], filtered['result']):
            for p_card in r[0]:
                p_df.append({'card': p_card, 'win': 1, 'loss': 0} if r[2] == 'win' else {'card': p_card, 'win': 0, 'loss': 1})
            for o_card in r[1]:
                o_df.append({'card': o_card, 'win': 1, 'loss': 0} if r[2] == 'loss' else {'card': o_card, 'win': 0, 'loss': 1})

        p_df = pd.DataFrame(p_df)
        o_df = pd.DataFrame(o_df)
        p_df = p_df.groupby('card').agg(np.sum)
        o_df = o_df.groupby('card').agg(np.sum)
        return p_df, o_df

    def generate_decklist_matchups(self, game_mode = 'ranked', game_threshold = 2):
        """
        Generates a dataframe with a list of cards, and the matchups where the card won and lost in the format of: ['card', 'p_deck_type', 'winning_matchups', 'losing_matchups']

        Keyword parameter:
        game_mode -- str, game type
        card_threshold -- int, the minimum amount of time the card has to show up

        Returns:
        cards -- pandas groupby object, with ['card', 'p_deck_type', 'o_deck_type', 'loss', 'win', 'win%']
        """
        cards = []
        gs = self.games
        if game_mode != 'both':
           gs = gs[gs['mode'] == game_mode]
        for r in zip(gs['p_cards_played'], gs['result'], gs['p_deck_type'], gs['o_deck_type']):
            for card in r[0]:
                data = {'card': card, 'p_deck_type': r[2], 'o_deck_type': r[3], 'win': 1, 'loss': 0} if r[1] == 'win' else {'card': card, 'p_deck_type': r[2], 'o_deck_type': r[3], 'win': 0, 'loss': 1}
                cards.append(data)
        cards = pd.DataFrame(cards)
        cards = cards.groupby(['card', 'p_deck_type', 'o_deck_type']).agg(np.sum)
        cards = cards[(cards['win'] + cards['loss']) > game_threshold]
        cards.loc[:, 'win%'] = cards['win']/(cards['win'] + cards['loss'])
        return cards


    def generate_card_stats(self, game_mode='ranked', game_threshold = 2):
        """
        Returns a groupby object with ['card', 'p_deck_type', 'o_deck_type', 'turn', 'loss', 'win'] as [str, str, str, int, int, int]
        Keyword parameters:
        game_mode -- str, the game type
        card_threshold -- str, the minimum amount of time the card has to show up

        Returns:
        cards -- pandas groupby object
        """
        cards = []
        gs = self.games
        if game_mode != 'both':
            gs = gs[gs['mode'] == game_mode]

        for r in zip(gs['card_history'], gs['result'], gs['p_deck_type'], gs['o_deck_type']):
            for play in r[0]:
                card = play['card']['name']
                player = play['player']
                turn = play['turn']
                result = {'win': 1, 'loss': 0} if r[1] == 'win' else {'win': 0, 'loss': 1}
                card_data = {'card': card,  'player': player, 'turn': turn}
                player_data = {'p_deck_type': r[2], 'o_deck_type': r[3]} if player == 'me' else {'p_deck_type': r[3], 'o_deck_type': r[2]}
                data = result.copy()
                data.update(card_data)
                data.update(player_data)
                cards.append(data)

        cards = pd.DataFrame(cards)
        cards = cards.groupby(['card', 'p_deck_type', 'o_deck_type', 'turn']).agg(np.sum)
        cards = cards[cards['win'] + cards['loss'] > game_threshold]
        cards.loc[:, 'win%'] = cards['win']/(cards['win'] + cards['loss'])
        return cards

    def create_heatmap(self, x, y, z, df, title, layout = None):
        """
        Creates a heatmap x, y, and z

        Keyword parameters:
        x -- str, name of the x value column
        y -- str, name of the y value column
        z -- str, name of the z value column

        Returns:
        graphs -- a list of one dictionary to be used with plotly.utils.PlotlyJSONEncoder
        """
        data = df.reset_index()
        data = data[[x, y, z]]
        x_vals = sorted(data[x].unique())
        y_vals = sorted(data[y].unique())
        x_vals = list(map(lambda x: x.replace('_', ' '), x_vals))
        y_vals = list(map(lambda x: x.replace('_', ' '), y_vals))
        data = data.pivot(x, y)
        z_vals = [data[x].values.tolist() for x in data.columns]
        titles = self.title_format(x, y, z)
        if layout == None:
            annotations = []
            for n, row in enumerate(z_vals):
                for m, val in enumerate(row):
                    var = z_vals[n][m]
                    annotations.append(
                        dict(
                            text = '{:.2f}'.format(val) if not pd.isnull(val) else '',
                            x = x_vals[m],
                            y = y_vals[n],
                            showarrow = False,
                            font = dict(color='white' if val < 0.7 else 'black')
                        )
                    )

            layout = dict(
                margin = dict(
                    l = 160,
                    b = 160
                ),
                height = 900,
                xaxis = dict(
                    title = titles[0]
                ),
                yaxis = dict(
                    title = titles[1]
                ),
                title = title,
                annotations = annotations
            )

        graphs = [
            dict(
                data = [
                    dict(
                        z = z_vals,
                        y = y_vals,
                        x = x_vals,
                        type = 'heatmap',
                        colorscale = 'Viridis'
                    )
                ],
                layout = layout
            )
        ]

        return graphs

    def create_stacked_chart(self, iter_column, x_col, y_col, df, layout = None):
        """
        Creates a stacked chart from a cards groupby object
        """
        if layout == None:
            layout = dict(
                margin = dict(
                    l = 160,
                    b = 160
                ),
                height = 900
            )
        x_vals = []
        y_vals = []
        for uniq_value in data.index.get_level_values(iter_column).tolist():
            x_vals.append(data.loc[uniq_value][x_col])
            y_vals.append(data.loc[uniq_value][y_col])
        data = []
        for i in zip(x_vals, y_vals):
            scatter = dict(
                x = i[0],
                y = i[1],
                fill='tozeroy'
            )
            data.append(scatter)
        graphs = [
            dict(
                data = data,
                layout = layout)
        ]
        return graphs

    def write_hdf5(self, hdf5_name):
        """
        Writes out self.games into a hdf5_file

        Keyword parameter:
        hdf5_name -- str, name of the hdf5 file
        """
        self.games.to_hdf('{}{}'.format(DATA_PATH, hdf5_name), 'table', append = False)


    def update_count(self, user_hash, total_items):
        """Updates the given total items count for the user with user_hash"""
        conn = sqlite3.connect('{}/users.db'.format(DATA_PATH))
        c = conn.cursor()
        c.execute('UPDATE users SET total_items = ?', (total_items,))
        conn.commit()
        conn.close()

    def store_data(self):
        """
        Stores the python data by using the filename as the sha5 hash of the username and api_key -> hash is stored in a database for lookups later, data is stored using the hdf5 format
        Table is in the format of ['user_hash', 'total_items', 'json_name', 'hdf5_name']

        Returns:
        user[1] -- int, total items
        user[2] -- str, json_name
        user[3] -- str, hdf5_name
        """
        user_hash = hashlib.sha1(('{}{}'.format(self.username, self.api_key)).encode()).hexdigest()
        conn = sqlite3.connect('{}/users.db'.format(DATA_PATH)) #TODO FIX THIS
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE user_hash = ?', (user_hash,))
        data = c.fetchall()
        if len(data) != 0:
            user = data[0]
        else:
            user = (user_hash, 0, '{}_j.json'.format(user_hash), '{}_h.hdf5'.format(user_hash))
            c.execute('INSERT INTO users VALUES (?, ?, ?, ?)', user)
        conn.commit()
        conn.close()
        return user[0], user[1], user[2], user[3]

    def read_data(self, json_name = None, hdf5_name = None):
        """
        Takes the names of the files and loads them into memory for processing

        Keyword parameter:
        json_name -- str, name of the json file
        hdf5_name -- str, name of the hdf5 file

        Returns:
        results -- dict, complete history of games and metadata
        """
        if json_name:
            with open("{}{}".format(DATA_PATH, json_name)) as json_data:
                results = json.load(json_data)
                self.history = results
        if hdf5_name:
            self.games = pd.read_hdf('{}{}'.format(DATA_PATH, hdf5_name), 'table')

    def check_data(self, json_name, hdf5_name):
        """
        Checks for the existance of either file under the DATA_PATH, returns False if either is missing

        Keyword parameter:
        json_name -- str
        hdf5 -- str

        Returns:
        bool -- False if either is missing, True otherwise
        """
        if os.path.isfile("{}{}".format(DATA_PATH, json_name)) and os.path.isfile("{}{}".format(DATA_PATH, hdf5_name)):
            return True
        else:
            return False


    def title_format(self, *titles):
        """
        Formats the titles

        Keyword parameter:
        *titles -- titles to be replaced

        Returns:
        titles_list -- list of replaced titles
        """
        titles_list = []
        for title in titles:
            if title == 'p_deck_type':
                titles_list.append('Player Deck Name')
            if title == 'o_deck_type':
                titles_list.append('Opponent Deck Name')
            if title == 'win%':
                titles_list.append('Win %')
        return titles_list

    def get_name_list(self):
        """
        Iterates through the database and creates a list of strings for deck names and card names

        Returns:
        deck_data -- list of str's, deck names
        card_data -- list of str's, card names
        """
        conn = sqlite3.connect(GRAPH_DATABASE)
        c = conn.cursor()
        c.execute('SELECT name, type FROM graphs')
        data = c.fetchall()
        deck_data = []
        card_data = []
        for row in data:
            if row[1] == 'deck':
                deck_data.append(row[0].replace('_', ' '))
            elif row[1] == 'card':
                card_data.append(row[0])
        conn.close()
        return deck_data, card_data

    def make_graph_data(self): #TODO: multithread this at some point & change to update instead of insert
        """
        Iterates through all the cards & decks above the game threshold, makes plotly json for each one
        """
        game_threshold = 5
        conn = sqlite3.connect(GRAPH_DATABASE)
        c = conn.cursor()
        graph_id = 0
        decks = map(lambda x: x.replace(' ', '_'), self._unique_decks())
        for deck in decks:
            data = self.generate_decklist_matchups(game_threshold = game_threshold).reset_index()
            data = data[data['p_deck_type'] == deck]
            graphs = self.create_heatmap('o_deck_type', 'card', 'win%', data, 'Win % of Cards in {}'.format(deck))
            graph_json = json.dumps(graphs, cls=plotly.utils.PlotlyJSONEncoder)
            graph_name = deck
            c.execute('INSERT INTO graphs VALUES(?, ?, ?, ?)', (graph_id, graph_name, graph_json, 'deck'))
            graph_id += 1
        conn.commit()
        cards = self._unique_cards()
        for card in cards:
            data = self.generate_card_stats(game_threshold = game_threshold)
            data = data.sum(level=['card', 'p_deck_type', 'o_deck_type']).loc[card]
            data.loc[:, 'win%'] = data['win']/(data['loss'] + data['win'])
            graphs = self.create_heatmap('o_deck_type', 'p_deck_type', 'win%', data, 'Win % of {}'.format(card))
            graph_json = json.dumps(graphs, cls=plotly.utils.PlotlyJSONEncoder)
            graph_name = card
            c.execute('INSERT INTO graphs VALUES(?, ?, ?, ?)', (graph_id, graph_name, graph_json, 'card'))
            graph_id += 1
        conn.commit()
        conn.close()

    def get_graph_data(self, name):
        """
        Returns plotly json for the specified name

        Keyword parameter:
        name -- str, name to match in the database

        Return:
        data -- str, plotly json data
        """
        conn = sqlite3.connect(GRAPH_DATABASE)
        c = conn.cursor()
        c.execute('SELECT json FROM graphs WHERE name = ?', (name,))
        data = c.fetchall()
        data = data[0][0]
        conn.close()
        return data
