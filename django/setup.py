from setuptools import setup, find_packages

# Read the contents of your README file
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="bgc_data_portal",  # Replace with your project name
    version="1.0.0",  # Start with a version number, e.g., 0.1.0
    description="A data portal to download, discover and analyse metagenomic BGC data",  # Short description
    long_description=long_description,  # This will include your README as the long description
    long_description_content_type="text/markdown",  # This is important to render Markdown on PyPI
    author="Santiago Sanchez",
    author_email="fragoso@ebi.ac.uk",
    url="https://github.com/Finn-Labb/bgc_data_portal",  # Replace with your GitHub repo URL
    packages=find_packages(
        exclude=["tests*"]
    ),  # Automatically find and include your packages
    include_package_data=True,  # Include files from MANIFEST.in
    install_requires=[
        "Django",  # Specify Django version compatible with your project
        "biopython",  # Biopython dependency
        "django-ninja",  # Django Ninja dependency
        "pandas",
        "numpy",
        "joblib",
        "seaborn",
        "requests",
        "plotly",
        "django-filter",
        "django-matomo==0.1.6",
    ],
    extras_require={
        "dev": [
            "jupyter",
            "quatro",
        ]
    },
    classifiers=[
        "Development Status :: 3 - Alpha",  # Adjust as per your project's status
        "Environment :: Web Environment",
        "Framework :: Django",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",  # Replace with your chosen license
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
    ],
    python_requires=">=3.9",  # Minimum Python version requirement
    keywords="django bioinformatics biopython ninja",
    license="MIT",  # Replace with your chosen license
    project_urls={},
)
