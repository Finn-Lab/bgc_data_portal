# create_genome_plot Guide
## Requirements
- plotly
- pandas

## Docs 

```
create_genome_plot(data, names, color_col=None, pattern_col=None, title="Genome Plot",
                   sequence_length=None, show_legend=True, color_map=None, pattern_shape_map=None,
                   palette=qualitative.Plotly, shape_height=0.2, **layout_kwargs)
```

The `create_genome_plot` function creates a genome plot using the Plotly library. It visualizes genomic features or annotations along a linear sequence.

Arguments:
- `data` (pandas.DataFrame): A DataFrame containing the genomic feature data. It should have the following columns:
  - `start` (int): The start position of each feature.
  - `stop` (int): The stop position of each feature.
  - `strand` (str): The strand information of each feature ('+' for forward strand, '-' for reverse strand).
  - Additional columns can be included for color and pattern mapping.
- `names` (str or list): The column name(s) in the `data` DataFrame to be used as the hover text for each feature.
- `color_col` (str, optional): The column name in the `data` DataFrame to be used for color mapping of the features. If not provided, a default color will be used.
- `pattern_col` (str, optional): The column name in the `data` DataFrame to be used for pattern mapping of the features. If not provided, no pattern will be applied.
- `title` (str, optional): The title of the genome plot. Default is "Genome Plot".
- `sequence_length` (int, optional): The total length of the genomic sequence. If not provided, it will be inferred from the maximum stop position in the `data`.
- `show_legend` (bool, optional): Whether to show the legend in the plot. Default is True.
- `color_map` (dict, optional): A dictionary mapping the unique values in the `color_col` to specific colors. If not provided, colors will be assigned automatically from the `palette`.
- `pattern_shape_map` (dict, optional): A dictionary mapping the unique values in the `pattern_col` to specific fill pattern shapes. If not provided, patterns will be assigned automatically.
- `palette` (list, optional): A list of colors to be used for automatic color assignment. Default is `qualitative.Plotly`.
- `shape_height` (float, optional): The height of each feature shape in the plot. Default is 0.2.
- `**layout_kwargs`: Additional keyword arguments to be passed to the `go.Layout` function for customizing the plot layout.

Returns:
- A Plotly Figure object representing the genome plot.

Example usage:
```python
import pandas as pd

data = pd.DataFrame({
    'start': [100, 200, 300],
    'stop': [150, 250, 350],
    'strand': ['+', '-', '+'],
    'feature_type': ['gene', 'promoter', 'gene'],
    'gene_name': ['geneA', 'promoterX', 'geneB']
})

fig = create_genome_plot(data, names='gene_name',
                         color_col='feature_type',
                         title='My Genome Plot')
fig.show()
```
