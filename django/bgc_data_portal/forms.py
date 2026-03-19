from django import forms
from django.core.validators import MinValueValidator, MaxValueValidator
from mgnify_bgcs.utils.lazy_loaders import get_highest_versions_by_tool
from mgnify_bgcs.utils.helpers import mgyb_converter

current_tool_versions = None


class MGYCSearchForm(forms.Form):
    mgyc_value = forms.CharField(label="Enter MGYC value", required=True)


class SequenceSearchForm(forms.Form):
    sequence = forms.CharField(
        label="Sequence in FASTA format",
        max_length=70000,
        required=True,
        widget=forms.Textarea(
            attrs={
                "placeholder": ">SEQ_ID\nATCGATCGATCGATCG...",
                "class": "form-control",
            }
        ),
    )

    sequence_type = forms.ChoiceField(
        choices=[("nucleotide", "Nucleotide"), ("protein", "Protein")],
        initial="nucleotide",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    unit_of_comparison = forms.ChoiceField(
        choices=[("bgc", "Whole BGC"), ("proteins", "Protein set (CDSs)")],
        initial="bgc",
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
    )

    similarity_measure = forms.ChoiceField(
        choices=[("hmmer", "HMMER / alignment"), ("cosine", "Cosine (embeddings)")],
        initial="hmmer",
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
    )

    similarity_threshold = forms.FloatField(
        label="Similarity threshold",
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
        widget=forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
    )

    set_similarity_threshold = forms.FloatField(
        label="Set similarity threshold (0–1). Dice coefficient for protein sets",
        required=False,  # We manage this manually in clean()
        initial=0.5,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        widget=forms.NumberInput(attrs={"step": "0.01", "class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        data = self.data if self.is_bound else self.initial

        sim = data.get("similarity_measure", "hmmer")
        if sim == "hmmer":
            self.fields["similarity_threshold"].initial = 32
            self.fields["similarity_threshold"].widget.attrs["step"] = 1
        else:
            self.fields["similarity_threshold"].initial = 0.85
            self.fields["similarity_threshold"].widget.attrs["step"] = 0.01

    def clean(self):
        cleaned_data = super().clean()
        unit = cleaned_data.get("unit_of_comparison")
        jaccard = cleaned_data.get("set_similarity_threshold")

        # Don't raise error even if jaccard is missing
        if unit == "proteins" and jaccard is None:
            # Supply a default if not provided
            cleaned_data["set_similarity_threshold"] = 0.5
        return cleaned_data


class BgcKeywordSearchForm(forms.Form):
    keyword = forms.CharField(
        max_length=255,
        required=False,
        label="Keyword",
        help_text="Search the data using keyword",
        # widget=forms.TextInput(attrs={
        #     'class': 'form-control custom-input',  # Add custom CSS class
        #     'style': 'width: 200px; margin-bottom: 10px;'  # Add inline styles for size and spacing
        # }
    )


class BgcAdvancedSearchForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Dynamically populate detector choices from the DB
        current_tool_versions = get_highest_versions_by_tool()
        if current_tool_versions:
            # Use detector names (tool names) as both value and label
            detector_choices = [(name, name) for name in current_tool_versions.keys()]

            self.fields["detectors"].choices = detector_choices
            # Preselect all names by default
            self.initial["detectors"] = [name for name, _ in detector_choices]
        else:
            self.fields["detectors"].choices = []
            self.initial["detectors"] = []

    bgc_class_name = forms.CharField(
        max_length=255,
        required=False,
        label="BGC Class Name",
        help_text="Classify BGCs by their biosynthetic type.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control custom-input",
                "style": "width: 200px; margin-bottom: 10px;",
            }
        ),
    )

    mgyb = forms.CharField(
        max_length=255,
        required=False,
        label="BGC Accession (MGYB)",
        help_text="Enter BGC accession (e.g., MGYB000000123456).",
        widget=forms.TextInput(
            attrs={
                "class": "form-control custom-input",
                "style": "width: 200px; margin-bottom: 10px;",
            }
        ),
    )

    assembly_accession = forms.CharField(
        max_length=255,
        required=False,
        label="Assembly Accession",
        help_text="Identifier for the assembled genome.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control custom-input",
                "style": "width: 200px; margin-bottom: 10px;",
            }
        ),
    )

    contig_accession = forms.CharField(
        max_length=255,
        required=False,
        label="Contig Accession",
        help_text="Contig that contains the BGC.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control custom-input",
                "style": "width: 200px; margin-bottom: 10px;",
            }
        ),
    )

    biome_lineage = forms.CharField(
        max_length=255,
        required=False,
        label="Biome Lineage",
        help_text="Ecological biome where the BGC was found.",
        widget=forms.TextInput(
            attrs={
                "class": "form-control custom-input",
                "style": "width: 200px; margin-bottom: 20px;",
            }
        ),
    )

    completeness = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={
                "class": "form-check-input custom-checkbox",
                "style": "margin-bottom: 10px;",
            }
        ),
        choices=[(0, "Complete BGC"), (1, "Single bounded"), (2, "Double bounded")],
        label="Select Completeness",
        help_text="Filter based on contig-edge truncation.",
        initial=[0, 1, 2],
    )

    protein_domain = forms.CharField(
        max_length=255,
        required=False,
        label="Domain (InterPro / Pfam)",
        help_text="Enter one or more domain accessions (comma or space-separated).",
        widget=forms.TextInput(
            attrs={
                "class": "form-control custom-input",
                "style": "width: 200px; margin-bottom: 5px;",
            }
        ),
    )

    domain_strategy = forms.ChoiceField(
        choices=[("intersection", "AND"), ("union", "OR")],
        required=False,
        label="Domain Strategy",
        initial="intersection",
        help_text="Choose AND for all domains, OR for any domain.",
        widget=forms.Select(
            attrs={
                "class": "form-control custom-input",
                "style": "width: 200px; margin-bottom: 20px;",
            }
        ),
    )

    detectors = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={
                "class": "form-check-input custom-checkbox",
                "style": "margin-bottom: 10px;",
            }
        ),
        choices=[],  # Populated in __init__ with detector names
        label="BGC Detectors",
        help_text="Filter by detector name. The latest version for each selected detector will be used.",
    )


class ChemicalStructureSearchForm(forms.Form):
    """
    The user can _either_ draw a molecule in JSME (→ hidden 'smiles')
    _or_ paste/type a SMILES string directly into 'smiles_text'. We pick one
    at submit time. Also include a similarity threshold.
    """

    similarity_threshold = forms.FloatField(
        label="Similarity threshold",
        min_value=0,
        max_value=1,
        initial=0.85,
        help_text="Tanimoto similarity 0 – 1.",
    )
    smiles_text = forms.CharField(
        label="Or enter SMILES string",
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": "e.g. CCO or c1ccccc1", "style": "width: 100%;"}
        ),
        # help_text="If you prefer, paste a SMILES string here instead of drawing."
    )
    smiles = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        help_text="(filled automatically from the drawing canvas)",
    )

    def clean(self):
        cleaned = super().clean()
        text = cleaned.get("smiles_text", "").strip()
        drawn = cleaned.get("smiles", "").strip()
        if not text and not drawn:
            raise forms.ValidationError(
                "Please either draw a molecule or paste its SMILES string."
            )
        # If both are given, prefer the typed SMILES
        if text:
            cleaned["smiles"] = text
        return cleaned


class BgcDetailsForm(forms.Form):
    bgc_id = forms.CharField(
        max_length=255,
        required=True,
        label="bgc_id",
        help_text="BGC accession or ID",
    )

    def clean_bgc_id(self):
        """Accept either an int or a string. If string is MGYB{:012} convert to int.

        Returns an int (pk) when cleaned.
        """
        from django.core.exceptions import ValidationError

        value = self.cleaned_data.get("bgc_id")

        # Allow programmatic ints
        if isinstance(value, int):
            return value

        if value is None:
            raise ValidationError("BGC id is required")

        raw = str(value).strip()
        if not raw:
            raise ValidationError("BGC id is required")

        # Accept plain integer strings
        if raw.isdigit():
            try:
                return int(raw)
            except (ValueError, TypeError):
                raise ValidationError("Invalid numeric BGC id")

        # Accept MGYB formatted strings (case-insensitive)
        up = raw.upper()
        if up.startswith("MGYB"):
            rest = up[4:]
            if len(rest) == 12 and rest.isdigit():
                try:
                    return mgyb_converter(up, text_to_int=True)
                except Exception:
                    raise ValidationError("Invalid MGYB accession format")
            else:
                raise ValidationError(
                    "MGYB accession must be in format MGYB followed by 12 digits"
                )

        raise ValidationError(
            "Provide either an integer BGC id or an accession like MGYB000000000001"
        )
