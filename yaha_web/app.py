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


# @app.route('/submit/<username>/<api_key>') #TODO - make this a real request
# def submit(username, api_key):
#     scrape = yaha_analyzer.yaha_analyzer()
#     scrape.grab_data(username, api_key)
#     response = make_response(scrape.games.to_csv())
#     response.headers['Content-Type'] = CSV_HEADER
#     return response

@app.route('/')
def index():
    scrape = yaha_analyzer.yaha_analyzer()
    scrape.open_collectobot_data()
    deck_data = scrape.unique_decks()
    card_data = scrape.unique_cards()
    game_count = len(scrape.games['hero'])
    return render_template('front.html', deck_data = deck_data, card_data = card_data, game_count = game_count)


@app.route('/matchups/<deck>')
def matchups(deck):
    deck = deck.replace(' ', '_')
    scrape = yaha_analyzer.yaha_analyzer()
    scrape.open_collectobot_data()
    graphs = scrape.create_cards_heatmap(deck, card_threshold=3)
    ids, graphJSON = generate_graph(graphs)

    game_count = len(scrape.games['hero'])
    return render_template('matchups.html', ids=ids, graphJSON=graphJSON, game_count = game_count)

#@app.route('/card/<card_name>')
#def card(card_name):



# @app.route('/matchups/<username>/<api_key>')
# def matchups(username, api_key):
#     scrape = yaha_analyzer.yaha_analyzer()
#     scrape.grab_data(username, api_key)
#     ids, graphJSON = generate_graph(scrape.create_matchup_heatmap(game_threshold=1))
#     return render_template('matchups.html', ids=ids, graphJSON=graphJSON)

# @app.route('/best_cards/<username>/<api_key>')
# def best_cards(username, api_key):
#     scrape = yaha_analyzer.yaha_analyzer()
#     scrape.grab_data(username, api_key)
#     ids, graphJSON = generate_graph(scrape.create_cards_heatmap('Dragon_Warrior'))
#     return render_template('matchups.html', ids=ids, graphJSON = graphJSON)


def generate_graph(graphs):
    ids = ['graph-{}'.format(i) for i, _ in enumerate(graphs)]
    graphJSON = json.dumps(graphs, cls=plotly.utils.PlotlyJSONEncoder)
    return ids, graphJSON
