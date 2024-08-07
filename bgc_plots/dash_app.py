# dash_apps/dash_app.py

from django_plotly_dash import DjangoDash
from dash import dcc, html
from dash.dependencies import Input, Output
import pandas as pd
import plotly.express as px

# Initialize the Dash app
app = DjangoDash('ScatterPlotApp')  # Dash instance in Django

# Sample DataFrame with URLs
df = pd.DataFrame(
    dict(
        x=[1, 2, 3],
        y=[2, 4, 6],
        urls=[
            "https://www.google.com",
            "https://www.plotly.com",
            "https://plotly.com/dash/",
        ],
    )
)

# Create the figure using Plotly Express and the custom_data attribute
fig = px.scatter(data_frame=df, x="x", y="y", custom_data=["urls"])

# Define the app layout
app.layout = html.Div(
    [
        dcc.Graph(
            id="figure",
            figure=fig
        ),
        html.Div(id="output", style={"margin-top": "20px"})
    ]
)

# Define the callback to update the link when a point is clicked
@app.callback(
    Output("output", "children"),
    [Input("figure", "clickData")]
)
def display_click_data(clickData):
    if clickData:
        # Extract the URL from the custom data
        url = clickData['points'][0]['customdata'][0]
        return html.A(f"Click here to visit: {url}", href=url, target="_blank")
    return "Click a point on the graph to visit a URL."

