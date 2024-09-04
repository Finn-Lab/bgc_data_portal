from django import forms

class BgcKeywordSearchForm(forms.Form):
    keyword = forms.CharField(
        max_length=255, 
        required=False, 
        label='Keyword',
        help_text='Search the data usning keyword',
        # widget=forms.TextInput(attrs={
        #     'class': 'form-control custom-input',  # Add custom CSS class
        #     'style': 'width: 200px; margin-bottom: 10px;'  # Add inline styles for size and spacing
        # }
        )


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
            (0, 'Complete BGC'),
            (1, 'Single bounded'),
            (2, 'Double bounded')
        ],
        label='Select Completeness',
        help_text='Filter BGCs detected by completeness. `Complete` indicates a BGC prediction fully contained within contig booundaries; `Single bounded` indicates if the BGC is truncated in one contig edge; `Double bounded` indicates if the BGC is truncated in both contig edges.',
        initial=[0,1,2]
    )
    
    protein_pfam = forms.CharField(
        max_length=255, 
        required=False, 
        label='Pfam',
        help_text='Enter one or more Pfam accession separated by comma or space. Pfam is a database of protein families, each represented by multiple sequence alignments and hidden Markov models (HMMs).',
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
        help_text='Choose "AND" to include BGCs that match all provided Pfams, or "OR" to include BGCs that match any Pfam.',
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
            ('antiSMASH', 'antiSMASH'),
            ('GECCO', 'GECCO'),
            ('SanntiS', 'SanntiS')
        ],
        label='BGC Detectors',
        help_text='Filter BGCs detected by the selected detectors.',
        initial=['antiSMASH','GECCO','SanntiS']
    )

    aggregate_strategy = forms.ChoiceField(
        choices=[('single', 'Single'), ('union', 'Union'), ('intersection', 'Intersection')],
        required=False,
        label='Aggregate Strategy',
        initial='single',
        help_text='Select the aggregate strategy for how results should be combined. See `Documentation` for detailed information',
        # widget=forms.TextInput(attrs={
            # 'class': 'form-control custom-input',  # Add custom CSS class
            # 'style': 'width: 200px; margin-bottom: 20px;'  # Add inline styles for size and spacing
        # })

    )


