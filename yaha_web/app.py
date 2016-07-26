from flask import Flask, make_response, render_template
import yaha_analyzer
import plotly.plotly as py
import plotly
import plotly.graph_objs as go
import json
import sys
import collectobot
CSV_HEADER = 'Content-Disposition'

app = Flask(__name__)

@app.route('/')
def index():
    scrape = yaha_analyzer.yaha_analyzer()
    deck_data, card_data = scrape.get_name_list()
    return render_template('front.html', deck_data=deck_data, card_data=card_data, game_count = 20)

@app.route('/card/<card_name>')
def card(card_name):
    scrape = yaha_analyzer.yaha_analyzer()
    graphJSON = scrape.get_graph_data(card_name)
    game_count = 20
    return render_template('matchups.html', graphJSON=graphJSON, game_count = game_count, name=card_name)

@app.route('/deck/<deck>')
def return_deck(deck):
    deck = deck.replace(' ', '_')
    scrape = yaha_analyzer.yaha_analyzer()
    graphJSON = scrape.get_graph_data(deck)

    game_count = 20
    return render_template('matchups.html', graphJSON = graphJSON, game_count = game_count, name=deck)


def generate_graph(graphs):
    ids = ['graph-{}'.format(i) for i, _ in enumerate(graphs)]
    graphJSON = json.dumps(graphs, cls=plotly.utils.PlotlyJSONEncoder)
    return ids, graphJSON

def remove_underscore(names):
    return list(map(lambda x: x.replace('_', ' '), names))

