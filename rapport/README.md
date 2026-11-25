# Sources du rapport

Le rapport `../2252046_2253227_Projet.docx` est généré, pas édité à la main.

| Fichier | Rôle |
|---|---|
| `ablation.py` | Mesure de l'élagage (figure 1) : écrit `ablation.json`. Environ 10 minutes. |
| `matches.json` | Scores des matchs locaux (figure 2), relevés dans `../Quoridor/tools/results/`. |
| `charts.py` | Produit `fig_pruning.png` et `fig_matches.png` (matplotlib requis). |
| `numbers.json` | Chiffres et phrases mesurés, insérés dans le texte. |
| `logo_polytechnique.jpg` | Logo de la page de couverture (repris du gabarit de page titre de Polytechnique). |
| `make_report.js` | Assemble le document Word (`npm install docx`, puis `node make_report.js ../2252046_2253227_Projet.docx`). |
| `render.ps1` | Ouvre le document dans Word, compte les pages et exporte un PDF. |

Les passages surlignés en jaune dans le document restent à compléter.
