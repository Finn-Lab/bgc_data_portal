from django import forms


class BgcAdvancedSearchForm(forms.Form):
    bgc_class_name = forms.CharField(
        max_length=255, 
        required=False, 
        label='BGC Class Name',
        help_text='The BGC Class name is used to classify the biosynthetic gene clusters based on their type.',
        widget=forms.TextInput(attrs={
            'class': 'form-control custom-input',  # Add custom CSS class
            'style': 'width: 200px; margin-bottom: 10px;'  # Add inline styles for size and spacing
        })
    )
    mgyb = forms.CharField(
        max_length=255, 
        required=False, 
        label='BGC Accession',
        help_text='The BGC Accession is the unique identifier assigned to a biosynthetic gene cluster.',
        widget=forms.TextInput(attrs={
            'class': 'form-control custom-input',  # Add custom CSS class
            'style': 'width: 200px; margin-bottom: 10px;'  # Add inline styles for size and spacing
        })

    )
    assembly_accession = forms.CharField(
        max_length=255, 
        required=False, 
        label='Assembly Accession',
        help_text='The Assembly accession is the identifier for the assembled sequence from which the BGC was predicted.',
        widget=forms.TextInput(attrs={
            'class': 'form-control custom-input',  # Add custom CSS class
            'style': 'width: 200px; margin-bottom: 10px;'  # Add inline styles for size and spacing
        })

    )
    mgyc = forms.CharField(
        max_length=255, 
        required=False, 
        label='Contig MGYC',
        help_text='The Contig MGYC is the identifier for the contig that contains the BGC.',
        widget=forms.TextInput(attrs={
            'class': 'form-control custom-input',  # Add custom CSS class
            'style': 'width: 200px; margin-bottom: 10px;'  # Add inline styles for size and spacing
        })

    )
    biome_lineage = forms.CharField(
        max_length=255, 
        required=False, 
        label='Biome Lineage',
        help_text='The Biome refers to the ecological community where the BGC was found.',
        widget=forms.TextInput(attrs={
            'class': 'form-control custom-input',  # Add custom CSS class
            'style': 'width: 200px; margin-bottom: 20px;'  # Add inline styles for size and spacing
        })

    )
    completeness = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input custom-checkbox',  # Add custom CSS class for styling
            'style': 'margin-bottom: 10px;'  # Add inline styles for spacing
        }),
        choices=[
            (0, 'Full-Length BGC'),
            (1, 'Single-Truncated'),
            (2, 'Double-Truncated')
        ],
        label='Select Detectors',
        help_text='Filter BGCs detected by completeness. Full-Length BGC indicates if the BGC is full-length; Single-Truncated indicates if the BGC is single-truncated; Double-Truncated indicates if the BGC is double-truncated.'
    )
    
    protein_pfam = forms.CharField(
        max_length=255, 
        required=False, 
        label='Pfam',
        help_text='Pfam is a database of protein families, each represented by multiple sequence alignments and hidden Markov models (HMMs).',
        widget=forms.TextInput(attrs={
            'class': 'form-control custom-input',  # Add custom CSS class
            'style': 'width: 200px; margin-bottom: 5px;'  # Add inline styles for size and spacing
        })

    )
    pfam_strategy = forms.ChoiceField(
        choices=[('intersection', 'AND'), ('union', 'OR')],
        required=False,
        label='Pfam Strategy',
        initial='intersection',
        help_text='Choose "AND" to include BGCs that match all Pfams, or "OR" to include BGCs that match any Pfam.',
        widget=forms.Select(attrs={
            'class': 'form-control custom-input',  # Add custom CSS class
            'style': 'width: 200px; margin-bottom: 20px;'  # Add inline styles for size and spacing
        })
    )

    detectors = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input custom-checkbox',  # Add custom CSS class for styling
            'style': 'margin-bottom: 10px;'  # Add inline styles for spacing
        }),
        choices=[
            ('antismash', 'antiSMASH'),
            ('gecco', 'GECCO'),
            ('sanntis', 'SanntiS')
        ],
        label='Select Detectors',
        help_text='Filter BGCs detected by the selected detectors.'
    )

    aggregate_strategy = forms.ChoiceField(
        choices=[('single', 'Single'), ('union', 'Union'), ('intersection', 'Intersection')],
        required=False,
        label='Aggregate Strategy',
        initial='single',
        help_text='Select the aggregate strategy for how results should be combined.',
        # widget=forms.TextInput(attrs={
            # 'class': 'form-control custom-input',  # Add custom CSS class
            # 'style': 'width: 200px; margin-bottom: 20px;'  # Add inline styles for size and spacing
        # })

    )


