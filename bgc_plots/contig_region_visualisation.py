# Copyright 2024 EMBL - European Bioinformatics Institute
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio  # Import the plotly.io module for HTML conversion
from django.http import Http404
from seaborn import color_palette
from api.utils import RegionFeatureError, get_region_features
from api.pfam_annots import pfamToGoSlim,pfam_desc # type: ignore


# Utility function to convert a seaborn color to a Plotly-compatible format
def seaborn_to_rgb_string(color):
    return f'rgb({int(color[0] * 255)}, {int(color[1] * 255)}, {int(color[2] * 255)})'

# Constants
# EXTENDED_NUCLEOTIDE_WINDOW = 10000

# Convert Seaborn color palette to a Plotly-compatible format
DEFAULT_ANNOT_COLOR = seaborn_to_rgb_string(color_palette('Set3')[2])
DEFAULT_CDS_COLOR = '#ffffff'  # This is already in a Plotly-compatible format

# Process GO Slim colors
sorted_go_slims = sorted({slim for slim_set in pfamToGoSlim.values() for slim in slim_set})
GO_SLIM_COLORS = {go_slim: seaborn_to_rgb_string(color_palette('husl', len(sorted_go_slims))[i]) 
                  for i, go_slim in enumerate(sorted_go_slims)}

# Process detector colors
DETECTOR_COLORS = {
    "Aggregated region": seaborn_to_rgb_string(color_palette('Set3')[8]),
    'SanntiS': seaborn_to_rgb_string(color_palette('Set3')[0]),
    'GECCO': seaborn_to_rgb_string(color_palette('Set3')[1]),
    'antiSMASH': seaborn_to_rgb_string(color_palette('Set3')[3]),
}

class ContigRegionViewer:
    """A class for visualizing contig regions in a biosynthetic gene cluster."""

    @staticmethod
    def format_data_for_plot(features_df) -> pd.DataFrame:
        """
        Retrieves and formats data for plotting a contig region.

        Args:
            pd.DataFrame: DataFrame containing the formatted feature data.
        """

        features_df['ID'] = features_df['attrib'].map(lambda x:x['ID'])
        
        legend_rank_dict = {
            'CLUSTER':0,
            'CDS':1,
            'ANNOT':2,
        }
        features_df['legend_rank'] = features_df['type'].map(legend_rank_dict)

        # what legend
        legend_trace_name_dict = {
            
            'CLUSTER':lambda x: x['source'],
            'CDS':lambda x: "CDS",
            'ANNOT':lambda x: x['attrib']['GOslim'][0] or 'Unknown GO',
        }
        features_df['legend_trace_name'] = [legend_trace_name_dict[r['type']](r) for _,r in features_df.iterrows()]

        # add color
        color_dict = {
            'CLUSTER':lambda x: DETECTOR_COLORS[x['source']],
            'CDS':lambda x: DEFAULT_CDS_COLOR,
            'ANNOT':lambda x: GO_SLIM_COLORS.get(x['attrib']['GOslim'][0], DEFAULT_ANNOT_COLOR),
        }
        features_df['color'] = [color_dict[r['type']](r) for _,r in features_df.iterrows()]

        # add legend_text
        legend_text_dict = {
            'CLUSTER':lambda x: x['source'],
            'CDS':lambda x: None,
            'ANNOT':lambda x: x['attrib']['description'],
        }
        features_df['legend_text'] = [legend_text_dict[r['type']](r) for _,r in features_df.iterrows()]

        return features_df

    @staticmethod
    def create_trace_data(start: int, end: int, strand: int, height: float = 0.001, 
                          _type: str = 'CDS', level_spacing: float = 1.5, 
                          arrow_prop: float = 0.15) -> tuple:
        """
        Creates trace data for plotting based on the feature's genomic coordinates and type.

        Args:
            start (int): Start position of the feature.
            end (int): End position of the feature.
            strand (int): Strand orientation (1 for positive, -1 for negative, 0 for none).
            height (float): Height of the trace.
            _type (str): Type of feature (e.g., 'CDS', 'ANNOT').
            level_spacing (float): Vertical spacing between levels.
            arrow_prop (float): Proportion of arrow head length to the total length.

        Returns:
            tuple: (xs, ys, _type) for plotting.
        """
        arrow_prop = 0 if strand == 0 else arrow_prop
        h = height / 2.0 * (1.7 if 'CDS' in _type else 1)
        x1, x2 = (start, end) if strand >= 0 else (end, start)
        arrow_length = abs(x2 - x1)
        delta = min(arrow_length * arrow_prop, 300)
        head_base = max(x1, x2 - delta) if strand >= 0 else min(x1, x2 + delta)
        level_offset = 0 * height * level_spacing  # Assuming single level; modify if multi-levels are needed
        ys = [level_offset - h, level_offset + h, level_offset + h, level_offset, level_offset - h, level_offset - h]
        xs = [x1, x1, head_base, x2, head_base, x1]
        return xs, ys, _type

    @staticmethod
    def create_bgc_plot(features_df: pd.DataFrame, names: str = 'ID', color_column: str = "color", 
                        show_legend: bool = True, legend_text_column: str = "legend_text", 
                        shape_height: float = 0.002, legend_rank_column: str = 'legend_rank', 
                        legend_trace_name_column: str = 'legend_trace_name', url_column: str = 'url',
                        background_color: str = "white", method_track_offset: float = 0.0005, 
                        **layout_kwargs):
        """
        Creates a plot for the biosynthetic gene cluster features.

        Args:
            features_df (pd.DataFrame): DataFrame containing the feature data.
            names (str): Column name to use for trace names.
            color_column (str): Column name for trace colors.
            show_legend (bool): Whether to show the legend.
            legend_text_column (str): Column name for legend text.
            shape_height (float): Height of the shapes in the plot.
            legend_rank_column (str): Column name for legend ranking.
            legend_trace_name_column (str): Column name for legend trace names.
            background_color (str): Background color for the plot.
            method_track_offset (float): Offset for method track vertical positioning.
            **layout_kwargs: Additional layout keyword arguments for customization.

        Returns:
            plotly.graph_objs.Figure: The generated plotly figure.
        """
        # Prepare data for plotting
        method_data = features_df[features_df['type'] == 'CLUSTER']
        non_method_data = features_df[features_df['type'] != 'CLUSTER']
        sequence_length = max(features_df["end"])
        sequence_start = min(features_df["start"])
        xaxis_range = [sequence_start - (sequence_length * 0.02), max(sequence_length, 23000)]

        # shape_height*=0.5
        # Compute trace data
        non_method_data[["xs", "ys", "types"]] = non_method_data.apply(
            lambda row: pd.Series(ContigRegionViewer.create_trace_data(
                row["start"], row["end"], row["strand"], height=shape_height, _type=row['type'])),
            axis=1
        )

        traces = []
        annotations = []
        added_legends = set()

        # Plot non-method features
        for _, row in non_method_data.sort_values(legend_rank_column).iterrows():
            color = row[color_column] if color_column else 'white'

            trace = go.Scatter(
                x=row["xs"],
                y=row["ys"],
                fill="toself",
                mode="lines",
                line=dict(color='black', width=3. if row['type'] == 'CDS' else 1.),
                fillcolor=color,
                text=f"{row['ID']}" + (f": {row['legend_text']}" if row['type'] != 'CDS' else '') ,#row[names],
                hoverinfo="text+x+y",
                name=row[legend_trace_name_column] if row['type'] != 'CDS' else 'Arrow',
                showlegend=row[legend_trace_name_column] not in added_legends,
                legendgroup='GO slim' if row['type'] != 'CDS' else 'CDS',#row[legend_text_column],
                legendgrouptitle_text='Pfam - GO slim' if row['type'] != 'CDS' else 'CDS',#row[legend_text_column],
                legendrank=row[legend_rank_column],
                customdata=("",row['attrib'].get('mgyp')),
            )
            added_legends.add(row[legend_trace_name_column])
            traces.append(trace)
            

        # Plot method tracks
        method_positions = [-(shape_height * 1.2) - i * method_track_offset for i in range(len(method_data))]
        for i, (_,row) in enumerate(method_data.sort_values([legend_rank_column,'source']).iterrows()):
            trace = go.Scatter(
                x=[row['start'], row['end']],
                y=[method_positions[i], method_positions[i]],
                mode="lines",
                line=dict(color=row[color_column], width=9.),
                hoverinfo="text",
                text=f"{row[names]}: {row['start']} - {row['end']}",
                showlegend= True,#row[legend_trace_name_column] not in added_legends,
                legendgroup='BGCs',#row[legend_text_column],
                legendgrouptitle_text='BGC',#row[legend_text_column],
                legendrank=row[legend_rank_column],
                name=row['source'],
                customdata=("",row['attrib'].get('mgyp')),
            )
            added_legends.add(row[legend_trace_name_column])
            traces.append(trace)

        # Layout adjustments
        layout = go.Layout(
            xaxis=dict(showgrid=False, zeroline=False, range=xaxis_range),
            yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, range=[min(method_positions) - shape_height, shape_height]),
            showlegend=show_legend,
            plot_bgcolor=background_color,
            paper_bgcolor=background_color,
            **layout_kwargs
        )

        return go.Figure(data=traces, layout=layout)

    @staticmethod
    def plot_contig_region(_features_df):
        """
        Creates a plot given a contig name and location.

        Args:
            contig_name (str): The name of the contig.
            start_position (int): The start position of the region.
            end_position (int): The end position of the region.

        Returns:
            HTML string of plotly.graph_objs.Figure: The generated plotly figure.
        """
        features_df = ContigRegionViewer.format_data_for_plot(_features_df)
        fig =  ContigRegionViewer.create_bgc_plot(features_df)
        html_str = pio.to_html(fig, full_html=False, div_id='bgc-plot')  # full_html=False to embed in an existing HTML structure
        return html_str
