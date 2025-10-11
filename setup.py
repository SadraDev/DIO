from setuptools import setup, find_packages

setup(
    name="two-hunters-trading-system",
    version="2.0.0",
    description="Advanced algorithmic trading system with Two Hunters strategy",
    author="Sadra Galavani",
    author_email="sadra.galavani78@gmail.com",
    packages=find_packages(),
    install_requires=[
        "click>=8.0.0",
        "pyyaml>=6.0",
        "pandas>=1.5.0",
        "numpy>=1.20.0",
        "MetaTrader5>=5.0.37",
        "matplotlib>=3.5.0",
        "mplfinance>=0.12.0",
        "scipy>=1.8.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "black>=22.0.0",
            "flake8>=5.0.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "two-hunters=main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
)