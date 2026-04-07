from setuptools import setup, find_packages

setup(
    name="officeqa-mcp",
    version="1.0.3",
    description="OfficeQA MCP Server - Treasury Bulletin analysis tools",
    author="OfficeQA Team",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=[
        "mcp>=0.1.0",
    ],
    entry_points={
        "console_scripts": [
            "officeqa-mcp=officeqa_mcp.server:main",
        ],
    },
)
