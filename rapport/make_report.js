// Report generator. Usage: node make_report2.js <out.docx>
// Numbers measured for this report come from numbers.json (written from the measurement scripts).
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, ImageRun, PageBreak,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle, LevelFormat, Footer, PageNumber,
  convertInchesToTwip,
} = require("docx");
const fs = require("fs");
const path = require("path");

const N = JSON.parse(fs.readFileSync(path.join(__dirname, "numbers.json"), "utf8"));

const FONT = "Calibri";
const BODY = 21;              // 10.5 pt
const SMALL = 20;             // 10 pt: tables and captions (the brief asks for 10 pt or more)
const PAGE_W = 12240, PAGE_H = 15840;
const MARGIN = convertInchesToTwip(0.9);
const CONTENT_W = PAGE_W - 2 * MARGIN;
const NAVY = "1F3864";

// Inline markup: **bold**, //italic//, [[to fill in]] (highlighted), ~sub~ (subscript)
// French typography: non-breaking spaces before : ; % » and after «, inside numbers, scores and units
function typo(text) {
  return text
    .replace(/(\d) (\d{3})(?!\d)/g, "$1 $2")
    .replace(/ ([:;%»?!])/g, " $1")
    .replace(/« /g, "« ")
    .replace(/(\d) – (\d)/g, "$1 – $2")
    .replace(/(\d) (s|ms|pas|fois|parties|positions|demi-coups|murs)(?![a-zà-ü])/g, "$1 $2")
    .replace(/ (→|−|×|÷|≈) /g, " $1 ");
}

function runs(text, base = {}) {
  text = typo(text);
  const out = [];
  const pattern = /(\*\*.+?\*\*|\/\/.+?\/\/|\[\[.+?\]\]|~.+?~|\^.+?\^)/g;
  for (const part of text.split(pattern)) {
    if (!part) continue;
    const opts = { font: FONT, size: BODY, ...base };
    if (part.startsWith("**")) out.push(new TextRun({ ...opts, text: part.slice(2, -2), bold: true }));
    else if (part.startsWith("//")) out.push(new TextRun({ ...opts, text: part.slice(2, -2), italics: true }));
    else if (part.startsWith("[[")) out.push(new TextRun({ ...opts, text: part.slice(2, -2), highlight: "yellow" }));
    else if (part.startsWith("~")) out.push(new TextRun({ ...opts, text: part.slice(1, -1), subScript: true }));
    else if (part.startsWith("^")) out.push(new TextRun({ ...opts, text: part.slice(1, -1), superScript: true }));
    else out.push(new TextRun({ ...opts, text: part }));
  }
  return out;
}

const p = (text, o = {}) => new Paragraph({
  spacing: { after: o.after ?? 100, before: o.before ?? 0, line: 240 },
  alignment: o.align ?? AlignmentType.JUSTIFIED,
  keepNext: o.keepNext,
  children: runs(text, { size: o.size ?? BODY, italics: o.italics, color: o.color }),
});
const bullet = (text) => new Paragraph({
  numbering: { reference: "puces", level: 0 },
  spacing: { after: 50, line: 240 },
  alignment: AlignmentType.JUSTIFIED,
  children: runs(text),
});
const h1 = (text) => new Paragraph({ text, heading: HeadingLevel.HEADING_1 });
const h2 = (text) => new Paragraph({ text, heading: HeadingLevel.HEADING_2 });
const caption = (text, o = {}) => new Paragraph({
  spacing: { after: o.after ?? 140, before: o.before ?? 40, line: 240 },
  alignment: AlignmentType.LEFT,
  keepNext: o.keepNext,
  children: runs(text, { size: SMALL, color: "404040" }),
});
const formula = (text) => new Paragraph({
  spacing: { after: 100, before: 40, line: 240 },
  alignment: AlignmentType.CENTER,
  children: runs(text, { italics: true }),
});

function figure(file, widthPx, ratio) {
  return new Paragraph({
    spacing: { after: 0, before: 60 },
    alignment: AlignmentType.CENTER,
    keepNext: true,
    children: [new ImageRun({
      type: "png",
      data: fs.readFileSync(path.join(__dirname, file)),
      transformation: { width: widthPx, height: Math.round(widthPx * ratio) },
    })],
  });
}

function table(headers, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const scaled = widths.map((w) => Math.round((w / total) * CONTENT_W));
  scaled[scaled.length - 1] += CONTENT_W - scaled.reduce((a, b) => a + b, 0);
  const line = { style: BorderStyle.SINGLE, size: 4, color: "BFC5CE" };
  const borders = { top: line, bottom: line, left: line, right: line };
  const cell = (text, i, head) => new TableCell({
    width: { size: scaled[i], type: WidthType.DXA },
    borders,
    shading: head ? { type: ShadingType.CLEAR, fill: "E8EDF3", color: "auto" } : undefined,
    margins: { top: 40, bottom: 40, left: 80, right: 80 },
    children: [new Paragraph({
      spacing: { after: 0, line: 240 },
      alignment: AlignmentType.LEFT,
      children: runs(String(text), { size: SMALL, bold: head }),
    })],
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: scaled,
    rows: [
      new TableRow({ tableHeader: true, cantSplit: true, children: headers.map((t, i) => cell(t, i, true)) }),
      ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((t, i) => cell(t, i, false)) })),
    ],
  });
}
const gap = (after = 100) => new Paragraph({ spacing: { after, line: 240 }, children: [] });

// ---------------------------------------------------------------------------------------------

const cover = [
  new Paragraph({ spacing: { before: 3200, after: 0 }, children: [] }),
  new Paragraph({ text: "Agent intelligent pour le jeu Quoridor", heading: HeadingLevel.TITLE, alignment: AlignmentType.CENTER }),
  p("Rapport de conception", { align: AlignmentType.CENTER, size: 28, color: NAVY, after: 700 }),
  p("INF8175 – Intelligence artificielle : méthodes et algorithmes", { align: AlignmentType.CENTER, size: 24, after: 60 }),
  p("Polytechnique Montréal – Automne 2026", { align: AlignmentType.CENTER, size: 24, after: 900 }),
  p("**Équipe sur Challonge :** [[À COMPLÉTER – nom d'équipe Challonge]]", { align: AlignmentType.CENTER, size: 24, after: 200 }),
  p("**Membres de l'équipe**", { align: AlignmentType.CENTER, size: 24, after: 60 }),
  p("Anders Antoine – matricule 2252046", { align: AlignmentType.CENTER, size: 24, after: 40 }),
  p("Adam Lecavalier – matricule 2253227", { align: AlignmentType.CENTER, size: 24, after: 0 }),
  new Paragraph({ children: [new PageBreak()] }),
];

const methodology = [
  h1("1. Méthodologie"),
  p("L'agent final (V5) est une recherche à variation principale avec approfondissement itératif, exécutée sur une représentation du plateau qui nous est propre et guidée par une évaluation réduite à deux termes. Cette sobriété est un aboutissement : chaque composante décrite ici a été conservée, et plusieurs autres retirées, à la suite d'une mesure rapportée à la section 3."),

  h2("1.1 Représentation du plateau"),
  p("La recherche n'opère pas sur les objets du moteur de jeu. Les cases sont des entiers (rangée × 9 + colonne), les passages fermés un masque de 4 bits par case, et tout coup est un entier unique : case d'arrivée, mur horizontal ou mur vertical. Un coup est joué puis défait sur place au lieu de copier l'état, et un hachage de Zobrist est mis à jour à chaque coup. Les distances au but sont calculées par A* avec l'heuristique admissible « rangées restantes » et une file à seaux, ce qui évite toute file de priorité. Le coût d'un nœud est ainsi passé de 38 ms (V1, appels au moteur) à 2,1 ms (V3), puis à environ " + N.ms_per_node + " ms (V5)."),
  p("Réimplémenter les règles crée un risque, puisqu'une action illégale coûte la partie. Deux garde-fous y répondent. Un test différentiel (//tools/test_rules.py//) compare notre plateau au moteur sur 240 positions aléatoires : déplacements avec sauts et diagonales, légalité de chacun des 162 emplacements de mur, distances, restauration exacte après un coup défait. À l'exécution, l'action retenue est en outre validée par le moteur lui-même, une fois par tour, avec repli sur son propre générateur."),

  h2("1.2 Génération et ordre des coups"),
  p("Un nœud ne considère que les murs qui touchent le plus court chemin courant de l'un des deux joueurs, 28 au plus. Un mur posé ailleurs ne modifie aucune distance : il ne peut servir qu'à préparer une barrière, ce que ce filtre ignore délibérément (limite discutée à la section 4). Le facteur de branchement moyen tombe ainsi à " + N.branching + " coups, contre plus de cent sans filtre. Les coups sont examinés dans cet ordre : (1) le coup mémorisé dans la table de transposition ; (2) le pas en avant sur notre plus court chemin ; (3) les murs, triés par leur gain mesuré — allongement du chemin adverse moins allongement du nôtre — dès que la profondeur restante atteint 3, et par coups « tueurs » et heuristique d'historique en dessous ; (4) les autres déplacements du pion."),

  h2("1.3 Recherche et élagage"),
  bullet("**Variation principale.** Le premier coup est cherché en fenêtre complète, les suivants en fenêtre nulle, avec nouvelle recherche seulement s'ils dépassent alpha."),
  bullet("**Table de transposition.** Indexée par la position seule, elle stocke la profondeur, la valeur, le type de borne (exacte, inférieure, supérieure) et le meilleur coup. Jusqu'à la V4, la clé contenait aussi la profondeur : l'approfondissement itératif ne transmettait donc aucun coup d'une passe à la suivante, défaut corrigé en V5. Une valeur de victoire ou de défaite n'est réutilisée qu'à profondeur égale (section 4)."),
  bullet("**Détection de symétrie.** Le plateau étant symétrique gauche-droite, la clé est le minimum du hachage de la position et de celui de son miroir, tenu à jour au même coût ; le coup mémorisé est reflété à la lecture. La correspondance a été dérivée de la sémantique des murs du moteur (mur horizontal : colonne c → 7 − c ; mur vertical : c → 9 − c) et vérifiée sur 164 paires de positions miroir, qui partagent toutes la même clé."),
  bullet("**Réductions des coups tardifs.** À profondeur restante 3 ou plus, les murs examinés après les quatre premiers coups sont d'abord cherchés un demi-coup moins profond, puis à pleine profondeur seulement s'ils dépassent alpha. C'est la seule composante qui ne préserve pas la valeur minimax."),
  bullet("**Distances héritées.** Un mur ne peut changer la distance d'un joueur que s'il ferme un passage de son plus court chemin ; sinon la distance du nœud parent est reprise sans nouveau calcul, et la légalité du mur (existence d'un chemin) n'est vérifiée que pour le joueur concerné. Les enfants d'un nœud de profondeur 1 sont évalués sur place, sans jouer le coup."),
  p("Hormis les réductions, toutes ces optimisations ne doivent changer que la vitesse. Un second test (//tools/test_search.py//) le vérifie : réductions désactivées, la recherche rend exactement la valeur d'un minimax sans élagage sur 120 couples (position, profondeur).", { before: 40 }),

  h2("1.4 Fonction d'évaluation"),
  formula("valeur = 100 × (d~adv~ − d~moi~) + 124 × (murs~moi~ − murs~adv~) ± 50"),
  p("où d est la longueur du plus court chemin vers le but, en centièmes de pas. Le dernier terme, un demi-pas en faveur du joueur au trait, rend comparables des feuilles de profondeurs différentes, ce que produisent les réductions."),
  p("Le poids des murs ne vient pas d'un réglage à la main. Nous avons d'abord ajusté une régression logistique sur 6 159 positions de parties, chacune étiquetée par l'issue de la partie (exactitude en validation 0,829, contre 0,504 pour la classe majoritaire). Les coefficients des deux distances sont −25,01 et +24,99 : leur symétrie valide la forme « différence de distances ». Le coefficient des murs, 31,67, signifie qu'un mur en main vaut 1,24 pas, alors que nos trois premières versions le comptaient pour 0,08 pas. Nous avons ensuite confirmé cette valeur par recherche locale (montée de colline sur le poids, la fonction objectif étant le score sur 80 parties à profondeur fixe avec ouvertures appariées) : aucune des six valeurs voisines essayées, de 84 à 164, n'a franchi le seuil d'acceptation de façon reproductible : la seule acceptée, 134 avec 57,5 %, est retombée à 49,4 % sur 160 parties de confirmation."),
  p("Deux termes présents en V4 ont été retirés. La mobilité recevait un coefficient négatif dans la régression. La « vulnérabilité » (allongement que le meilleur mur adverse peut nous imposer) occupait 69 % du temps de recherche de la V4 et dupliquait ce que la recherche explore déjà : appliquée à la racine, elle a fait chuter le score à 28 % (figure 2)."),

  h2("1.5 Gestion des 15 minutes"),
  formula("budget = min( temps utile ÷ coups restants estimés ; plafond ; 20 % du temps utile )"),
  p("Le temps utile est le temps restant moins 3 s de marge pour la latence de communication, et le nombre de coups restants est estimé par max(12, notre distance + nos murs en main). Le plafond vaut 20 s en général, 1 s pendant les quatre premiers demi-coups tant qu'aucun mur n'est posé (l'avance y est forcée), et 0,5 s lorsque plus personne n'a de mur (course pure, sans décision). Le troisième terme impose une décroissance géométrique : le temps ne peut pas s'épuiser, quelle que soit la durée de la partie."),
  p("À l'intérieur d'un coup, le chronomètre démarre à la première ligne de //compute_action// et l'horloge est relue tous les 256 nœuds. Aucune nouvelle passe n'est lancée une fois 45 % du budget écoulés, car une passe coûte environ " + N.pass_ratio + " fois la précédente. Une passe interrompue n'est pas perdue : elle examine en premier le meilleur coup de la passe précédente, si bien que son meilleur coup provisoire est au moins aussi bon. " + N.time_sentence),

  h2("1.6 Garde anti-répétition"),
  p("Revenir sur l'une de nos six dernières cases coûte 0,32 pas divisé par l'ancienneté de la case, et cette pénalité croît au-delà du 150^e^ demi-coup. Elle est appliquée à la racine seulement : l'historique de la partie est la seule information que la recherche ne voit pas, et l'introduire dans l'arbre fausserait les valeurs de la table de transposition. Son origine est décrite à la section 2."),
];

const evolution = [
  h1("2. Évolution de l'agent"),
  caption("**Tableau 1.** Les cinq versions soumises sur Abyss.", { keepNext: true, before: 0, after: 60 }),
  table(
    ["Version", "Nom sur Abyss", "Changement par rapport à la précédente"],
    [
      ["V1", "Agent1", "Minimax alpha-bêta avec approfondissement itératif et table de transposition à bornes, sur les objets du moteur. Évaluation : distances, murs (0,08 pas), mobilité."],
      ["V2", "Agent_V2", "Ajout simultané d'une recherche de quiescence, de la symétrie miroir, d'un comptage de chemins et d'une pénalité de répétition."],
      ["V3", "v3_agent, puis AgentFastboard_V3", "Retour à l'essentiel : trois défauts de gestion du temps corrigés, puis plateau dédié (masques de bits, coups joués et défaits, Zobrist, A*) qui divise le coût d'un nœud par 18."],
      ["V4", "Agent_V4_combined (rejeté), puis Agent_V4_fixed", "Travail sur l'évaluation : poids des murs ajusté par régression (0,08 → 1,24 pas), terme de vulnérabilité, nouvelle courbe de temps ; puis garde anti-répétition et clés de transposition symétriques."],
      ["V5", "[[À COMPLÉTER]]", "Moteur de recherche réécrit : variation principale, table indexée par la position, réductions des coups tardifs, distances héritées. Évaluation ramenée à deux termes, poids confirmé par recherche locale."],
    ],
    [8, 24, 68],
  ),
  gap(80),
  p("**V1 → V2 → V3.** La V2 empilait cinq mécanismes sans mesure intermédiaire. Au budget réel, elle jouait des coups de plusieurs centaines de secondes, et sa table de symétrie reflétait mal les murs verticaux (c → 8 − c au lieu de 9 − c : 35 positions non équivalentes confondues sur 298). La V3 a pris la direction inverse : rendre le temps prévisible et la recherche rapide avant d'ajouter quoi que ce soit. Le diagnostic a isolé trois causes de dépassement — 713 ms de travail avant le démarrage du chronomètre, une formule pouvant accorder 225 s à un seul coup, une horloge relue toutes les 38 ms seulement — et ramené le dépassement maximal d'un facteur 6,3 à 1,2."),
  p("**V3 → V4.** La V3 doublait la profondeur atteinte (2 → 4 demi-coups) sans gagner davantage contre la V1 (10 – 10). Nous en avons conclu que l'évaluation était le facteur limitant et y avons consacré la V4. Sa première soumission a été rejetée par Abyss après une partie de 2 992 demi-coups. Aucune limite de temps n'avait cédé (295 s utilisées sur 900, coup le plus long de 15,0 s) : notre pion était perdant dans toutes les lignes, et comme une défaite lointaine est mieux notée qu'une défaite proche, faire la navette était le coup le mieux évalué, face à un adversaire qui temporisait lui aussi. La garde anti-répétition de la section 1.6 corrige ce comportement : rejouée depuis la position finale réelle, la V4 d'origine visite 2 cases en 250 coups, la version corrigée termine en 100 demi-coups."),
  p("**V4 → V5.** Sur Abyss, la V4 n'a gagné que 12 parties sur 30. L'analyse de ces parties (section 3.3) montre que les adversaires gagnent par des barrières de plusieurs murs, hors de portée d'une recherche à 4 ou 5 demi-coups. Deux pistes s'offraient : enrichir l'évaluation pour estimer ces barrières, ou chercher plus profond. Un prototype de la première (potentiel multi-murs, évaluation par simulation de fin de partie) a perdu 2 – 4 puis 0 – 4 contre la V4 ; la V4 dotée de 6 s par coup l'emportait en revanche environ deux fois sur trois sur la V4 limitée à 0,4 s. La V5 mise donc tout sur la profondeur."),
];

const results = [
  h1("3. Résultats"),
  p("Nous utilisons quatre critères : le nombre de positions visitées pour terminer une profondeur donnée, qui mesure l'efficacité de l'élagage ; le score en match, avec couleurs alternées, ouvertures appariées et intervalle de confiance de Wilson à 95 % ; la proportion de positions où deux versions choisissent un coup différent ; et, sur les parties exportées d'Abyss, la trajectoire des distances au but. Les trois derniers sont produits par nos outils //arena.py//, //behaviour_diff.py// et //analyse_games.py//."),

  h2("3.1 Efficacité de l'élagage"),
  figure("fig_pruning.png", 640, N.fig_pruning_ratio),
  caption("**Figure 1.** Positions visitées pour terminer chaque profondeur, moyenne géométrique sur " + N.positions + " positions tirées de parties de l'agent contre lui-même. Pour les trois variantes de recherche, le compte cumule toutes les passes de l'approfondissement itératif."),
  p(N.pruning_text),

  h2("3.2 Matchs entre versions"),
  p("La figure 2 rassemble tous nos matchs. Trois lectures s'en dégagent. **La mesure est le goulot d'étranglement.** À 36 parties, l'intervalle couvre environ ±16 points : ni la vulnérabilité (47 %) ni le poids des murs seul (56 %) ne sont départagés, et c'est leur combinaison sur 51 parties qui a justifié la V4. **Les idées plausibles échouent souvent.** L'évaluation exacte des fins de partie ne changeait aucune décision (0 position sur 65) ; le comptage de chemins est nuisible à deux calibrages différents (57/136) ; la vulnérabilité à la racine est le seul résultat nettement négatif. Le test de décisions modifiées, qui coûte une minute au lieu de trente, nous a évité plusieurs matchs inutiles. **La V5 est le seul saut net** : " + N.v5_sentence),
  figure("fig_matches.png", 640, N.fig_matches_ratio),
  caption("**Figure 2.** Score de chaque variante contre la version indiquée (une partie nulle compte pour un demi-point). Budgets par agent et par partie : de 10 à 900 s selon le match, identiques pour les deux joueurs."),
  p("La détection de symétrie mérite une mention honnête : correcte et gratuite, elle n'apporte presque rien en jeu (15 – 15, table de taille inchangée à 0,1 % près). Une position et son miroir ne se rencontrent dans le même arbre que tant que le plateau est lui-même symétrique, c'est-à-dire pendant les tout premiers coups."),

  h2("3.3 Parties sur Abyss"),
  caption("**Tableau 2.** Bilan sur Abyss. [[Relevé du 5 novembre 2026 (V4 : parties exportées au 9 novembre) – à actualiser avant la remise.]]", { keepNext: true, before: 0, after: 60 }),
  table(
    ["Agent", "Version", "Victoires – défaites", "Elo"],
    [
      ["Agent1", "V1", "372 – 362", "815"],
      ["Agent_V2", "V2", "372 – 345", "1183"],
      ["AgentFastboard_V3", "V3", "155 – 136", "1244"],
      ["Agent_V4_combined", "V4 (rejetée)", "5 – 3", "1040"],
      ["Agent_V4_fixed", "V4 corrigée", "12 – 18 (parties exportées)", "[[À COMPLÉTER]]"],
      ["[[À COMPLÉTER]]", "V5", "[[À COMPLÉTER]]", "[[À COMPLÉTER]]"],
    ],
    [30, 20, 32, 18],
  ),
  gap(80),
  p("Les parties exportées ont été plus instructives que nos matchs locaux. Avant la V4, nos neuf défaites analysées suivent le même scénario : notre pion arrive à 1 à 5 pas du but par un chemin unique, puis l'adversaire l'enferme et la distance remonte à 8 – 26 pas. Sur les 30 parties de la V4, tout se joue encore sur l'enfermement, et le décompte des murs en donne la raison : le premier mur d'un joueur rapporte en moyenne 1,0 pas net, les murs 6 à 10 entre 2,5 et 3,1 pas. Les murs ont des rendements croissants, parce qu'une barrière ne coûte cher à contourner qu'une fois presque fermée. Nos adversaires posent en moyenne 9,5 murs par partie, le premier vers le 9^e^ demi-coup ; la V4 en posait 7,8, le premier vers le 13^e^, et terminait 11 de ses 18 défaites avec des murs inutilisés. Comme un mur en main vaut 1,24 pas dans notre évaluation, soit plus que le gain d'un premier mur, seule une recherche assez profonde pour voir le troisième ou le quatrième mur peut justifier de commencer la barrière."),
];

const discussion = [
  h1("4. Discussion"),
  p("**Avantages.** L'agent final est rapide, " + N.depth_sentence + " Il est vérifiable : deux tests automatiques établissent que le plateau respecte les règles du moteur et que la recherche rend la valeur minimax, ce qui nous a permis de réécrire le moteur en V5 sans régression silencieuse. Son temps de calcul est borné par construction et il ne peut pas rendre d'action illégale. Enfin, son évaluation ne compte que trois constantes, toutes issues d'une mesure."),
  p("**Limites.** (1) L'horizon demeure : une barrière de quatre ou cinq murs dépasse encore la profondeur atteinte en début de partie, et le filtre des murs candidats exclut les murs de pure préparation. Rejouée sur 72 positions de début de parties perdues sur Abyss, la V5 choisit un mur 19 fois contre 23 pour la V4 : elle calcule mieux, mais n'engage pas plus tôt la guerre de murs. (2) Nos preuves sont locales. La V5 domine nos versions précédentes, pas nécessairement les agents d'Abyss ; la V4 l'emportait aussi 39 – 12 localement avant de ne gagner que 12 parties sur 30 en ligne. (3) Le poids des murs est un optimum mesuré contre l'agent lui-même, à profondeur fixe. " + N.limit_sentence),
  p("**Pistes d'amélioration.** La plus directe est une extension sélective de la recherche le long des séquences de murs forcées, pour suivre une barrière jusqu'à sa fermeture au lieu de s'arrêter à profondeur fixe. Viennent ensuite un terme d'évaluation estimant le coût de fermeture d'une barrière entamée, à condition qu'il reste assez peu coûteux pour ne pas reproduire l'échec de la vulnérabilité ; un ajustement des poids sur des parties d'Abyss plutôt que sur l'auto-jeu ; et un petit livre d'ouvertures construit hors ligne, la détection de symétrie y étant justement utile pendant les premiers coups."),
];

const references = [
  new Paragraph({ children: [new PageBreak()] }),
  h1("Références"),
  p("[1] G. Slatton, « Solving Quoridor », billet technique, grantslatton.com/solving-quoridor (consulté en novembre 2026). Forme de l'évaluation, symétrie miroir.", { align: AlignmentType.LEFT }),
  p("[2] C. Jose, S. Kulshrestha, C. Ling, X. Liu et B. Moskowitz, « Quoridor-AI », rapport de projet du cours CMSC727. Comparaison minimax, MCTS et apprentissage par renforcement.", { align: AlignmentType.LEFT }),
  p("[3] L. Glendenning, « Mastering Quoridor », mémoire de baccalauréat, University of New Mexico, 2005. Caractéristiques d'évaluation pour Quoridor.", { align: AlignmentType.LEFT }),
  p("[4] Notes de cours INF8175, Polytechnique Montréal, automne 2026 : modules 2 (recherche avec information), 3 (recherche en situation d'adversité) et 4 (recherche locale).", { align: AlignmentType.LEFT }),
];

const doc = new Document({
  numbering: {
    config: [{
      reference: "puces",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 300, hanging: 200 } } },
      }],
    }],
  },
  styles: {
    default: {
      document: { run: { font: FONT, size: BODY } },
      title: {
        run: { font: FONT, size: 52, bold: true, color: NAVY },
        paragraph: { spacing: { before: 0, after: 120 }, keepNext: true },
      },
      heading1: {
        run: { font: FONT, size: 26, bold: true, color: NAVY },
        paragraph: { spacing: { before: 200, after: 90 }, keepNext: true },
      },
      heading2: {
        run: { font: FONT, size: 22, bold: true, color: "2E4B7A" },
        paragraph: { spacing: { before: 130, after: 60 }, keepNext: true },
      },
    },
  },
  sections: [{
    properties: {
      page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } },
      titlePage: true,
    },
    footers: {
      first: new Footer({ children: [new Paragraph({ children: [] })] }),
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ font: FONT, size: 20, color: "666666", children: ["Équipe 50 – INF8175 – ", PageNumber.CURRENT] })],
        })],
      }),
    },
    children: [...cover, ...methodology, ...evolution, ...results, ...discussion, ...references],
  }],
});

Packer.toBuffer(doc).then((b) => {
  fs.writeFileSync(process.argv[2], b);
  console.log("written:", process.argv[2], b.length, "bytes");
});
