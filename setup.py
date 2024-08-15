from setuptools import setup, find_packages
from bgc_data_portal import __version__,__name__,__description__

# Read the contents of your README file
from pathlib import Path
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="your_django_project",  # Replace with your project name
    version="0.1.0",  # Start with a version number, e.g., 0.1.0
    description="A Django project for bioinformatics using Biopython and Ninja",  # Short description
    long_description=long_description,  # This will include your README as the long description
    long_description_content_type="text/markdown",  # This is important to render Markdown on PyPI
    author="Your Name",
    author_email="your.email@example.com",
    url="https://github.com/yourusername/your_django_project",  # Replace with your GitHub repo URL
    packages=find_packages(exclude=["tests*"]),  # Automatically find and include your packages
    include_package_data=True,  # Include files from MANIFEST.in
    install_requires=[
        "Django",  # Specify Django version compatible with your project
        "biopython",  # Biopython dependency
        "django-ninja",  # Django Ninja dependency
        'pandas',
        'numpy',
        'joblib',
        'seaborn',
        'requests',
        'plotly',
        # '',
        # '',
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",  # Adjust as per your project's status
        "Environment :: Web Environment",
        "Framework :: Django",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",  # Replace with your chosen license
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
    ],
    python_requires='>=3.7',  # Minimum Python version requirement
    keywords="django bioinformatics biopython ninja",
    license="MIT",  # Replace with your chosen license
    project_urls={
        "Bug Tracker": "https://github.com/yourusername/your_django_project/issues",
        "Documentation": "https://github.com/yourusername/your_django_project/wiki",
        "Source Code": "https://github.com/yourusername/your_django_project",
    },
)
