import plotly.graph_objs as go
from django.shortcuts import render

                  
# def plot_view(request):
#     # Sample data
#     x_data = [1, 2, 3, 4, 5]
#     y_data = [10, 11, 12, 13, 14]
#     urls = ['http://example.com/1', 'http://example.com/2', 'http://example.com/3', 'http://example.com/4', 'http://example.com/5']

#     # Create a Plotly figure with Scatter plot
#     fig = go.Figure(data=[go.Scatter(x=x_data, y=y_data, mode='markers', marker=dict(size=10))])

#     # Adding annotations for clickable points
#     annotations = []
#     for i in range(len(x_data)):
#         annotations.append(dict(
#             x=x_data[i],
#             y=y_data[i],
#             text="""<a href="https://plot.ly/">{}</a>""".format("Text"),
#             # text=f"""<a href="https://plot.ly/">Text</a>""",
#             showarrow=True,
#             xanchor='center',
#             yanchor='middle',
#             xref='x',
#             yref='y'
#         ))

#     # Update the layout with annotations
#     fig.update_layout(
#         annotations=annotations,
#         # plot_bgcolor='rgba(0, 0, 0, 0)',
#     )
#     plot_div = fig.to_html(full_html=False)

#     # Render the plot in the template
#     return render(request, 'bgc_plots/graph.html', context={'plot_div': plot_div})

def plot_view(request):
    """
    Render the template that contains the embedded Dash app.
    """
    return render(request, 'bgc_plots/plot.html')