import plotly.graph_objs as go
from plotly.subplots import make_subplots
from collections import Counter
from plotly.offline import plot

def generate_horizontal_bar_plot_html(counter_list, titles):
    """
    Generate a Plotly plot with multiple horizontal barplot subplots from a list of Counter objects.
    
    Args:
    - counter_list: List of Counter objects
    - titles: List of titles for each subplot
    
    Returns:
    - HTML string of the plot
    """
    # Number of subplots needed
    num_subplots = len(counter_list)
    
    # Create subplots: 1 row, multiple columns
    fig = make_subplots(rows=1, cols=num_subplots, subplot_titles=titles)
    
    # Add horizontal bar plots for each Counter object
    for i, counter in enumerate(counter_list):
        x_values = list(counter.values())
        y_values = list(counter.keys())
        
        fig.add_trace(
            go.Bar(
                x=x_values,
                y=y_values,
                orientation='h',  # Horizontal bars
                marker=dict(color='black'),  # Black bars
                hoverinfo='x+y',  # Show both x (count) and y (category) on hover
            ),
            row=1, col=i+1
        )
    
    # Update layout to meet the styling and size requirements
    fig.update_layout(
        height=400,  # 30% vertical
        width=900,  # 70% horizontal
        plot_bgcolor='white',  # White background
        paper_bgcolor='white',  # White surrounding background
        title_text="Multiple Horizontal Barplot Subplots",
        showlegend=False,
        margin=dict(l=40, r=40, t=40, b=40),
        font=dict(color='black')  # Black font for titles and axes
    )
    
    # Adjust subplot spacing
    fig.update_yaxes(showline=True, linecolor='black', gridcolor='lightgrey')  # Black axis lines
    fig.update_xaxes(showline=True, linecolor='black', gridcolor='lightgrey')  # Black axis lines
    
    # Generate the HTML for the plot
    plot_html = plot(fig, output_type='div')
    
    return plot_html
