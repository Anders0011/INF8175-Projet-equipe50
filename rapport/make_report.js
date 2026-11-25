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

// Cover page laid out like Polytechnique's usual title page: logo, course, project, authors, date
const coverLine = (text, o = {}) => new Paragraph({
  spacing: { before: o.before ?? 0, after: o.after ?? 0, line: 240 },
  alignment: o.align ?? AlignmentType.RIGHT,
  children: runs(text, { font: o.font ?? "Arial", size: o.size ?? 24, bold: o.bold, italics: o.italics, color: o.color }),
});
const cover = [
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 0 },
    children: [new ImageRun({
      type: "jpg",
      data: fs.readFileSync(path.join(__dirname, "logo_polytechnique.jpg")),
      transformation: { width: 300, height: 143 },
    })],
  }),
  coverLine("INF8175", { align: AlignmentType.CENTER, font: FONT, size: 48, before: 1500 }),
  coverLine("Intelligence artificielle : méthodes et algorithmes", { align: AlignmentType.CENTER, font: FONT, size: 48 }),
  coverLine("Projet Quoridor : rapport de conception", { font: FONT, size: 28, color: "595959", before: 1400 }),
  coverLine("Soumis par :", { bold: true, before: 2600, after: 40 }),
  coverLine("Antoine, Anders - 2252046", { italics: true, after: 40 }),
  coverLine("Lecavalier, Adam - 2253227", { italics: true, after: 40 }),
  coverLine("Équipe 50 sur Challonge", { italics: true }),
  coverLine("3 décembre 2026", { italics: true, before: 700 }),
  new Paragraph({ children: [new PageBreak()] }),
];

const methodology = [
  h1("1. Méthodologie"),
  p("L'agent final (V5) repose sur une recherche alpha-bêta à variation principale avec approfondissement itératif [4]. Elle utilise notre propre représentation du plateau et une fonction d'évaluation à deux termes. Cette simplicité est volontaire : nous avons conservé les composantes qui ont résisté aux mesures et retiré les autres, comme le montrent les résultats de la section 3."),

  h2("1.1 Représentation du plateau"),
  p("La recherche ne manipule pas les objets du moteur de jeu. Une case est un entier (rangée × 9 + colonne), les passages fermés forment un masque de 4 bits par case, et chaque coup est un entier : case d'arrivée, mur horizontal ou mur vertical. Un coup est joué puis défait sur place, sans copier l'état, et un hachage de Zobrist est mis à jour à chaque coup. Les distances au but sont calculées par A* [4], avec l'heuristique admissible « rangées restantes » et une file à seaux au lieu d'une file de priorité. Un nœud coûtait 38 ms en V1 (appels au moteur), 2,1 ms en V3 et environ " + N.ms_per_node + " ms en V5."),
  p("Réimplémenter les règles comporte un risque, puisqu'une action illégale fait perdre la partie. L'agent s'en protège à l'exécution : avant d'être rendue, l'action choisie est validée par le moteur lui-même, une fois par tour, et si elle est refusée l'agent se rabat sur le générateur du moteur. Pendant le développement, nous avons aussi comparé notre plateau au moteur sur 240 positions aléatoires : déplacements avec sauts et diagonales, légalité des 162 emplacements de mur, distances, et état exact après un coup défait."),

  h2("1.2 Génération et ordre des coups"),
  p("Un nœud ne considère que les murs qui touchent le plus court chemin actuel de l'un des deux joueurs, 28 au plus. Un mur posé ailleurs ne change aucune distance ; il ne sert qu'à préparer une barrière, ce que ce filtre ignore volontairement (voir la section 4). Le facteur de branchement moyen descend ainsi à " + N.branching + " coups, contre plus de cent sans filtre. Les coups sont examinés dans cet ordre : (1) le coup gardé dans la table de transposition ; (2) le pas en avant sur notre plus court chemin ; (3) les murs, triés par leur gain mesuré (allongement du chemin adverse moins allongement du nôtre) quand il reste au moins 3 demi-coups à chercher, et par coups « tueurs » et historique en dessous ; (4) les autres déplacements du pion."),

  h2("1.3 Recherche et élagage"),
  bullet("**Variation principale.** Le premier coup est cherché avec une fenêtre complète, les suivants avec une fenêtre nulle, et un coup n'est recherché à nouveau que s'il dépasse alpha."),
  bullet("**Table de transposition.** Indexée par la position seule, elle garde la profondeur, la valeur, le type de borne (exacte, inférieure, supérieure) et le meilleur coup. Jusqu'à la V4, la clé contenait aussi la profondeur, si bien que l'approfondissement itératif ne transmettait aucun coup d'une passe à la suivante ; la V5 corrige ce défaut. Une valeur de victoire ou de défaite n'est réutilisée qu'à la même profondeur (section 4)."),
  bullet("**Détection de symétrie.** Le plateau est symétrique de gauche à droite, une propriété que Slatton exploite déjà dans son étude de Quoridor [1]. La clé est le minimum entre le hachage de la position et celui de son miroir, tenu à jour au même coût, et le coup gardé est reflété à la lecture. Nous avons dérivé la correspondance de la façon dont le moteur place les murs (mur horizontal : colonne c → 7 − c ; mur vertical : c → 9 − c), puis vérifié que 164 paires de positions miroir partagent toutes la même clé."),
  bullet("**Réductions des coups tardifs.** Quand il reste au moins 3 demi-coups, les murs examinés après les quatre premiers coups sont d'abord cherchés un demi-coup moins profond, puis à pleine profondeur s'ils dépassent alpha. C'est la seule composante qui peut changer la valeur minimax."),
  bullet("**Distances héritées.** Un mur ne change la distance d'un joueur que s'il ferme un passage de son plus court chemin. Sinon, la distance du nœud parent est reprise telle quelle, et l'existence d'un chemin n'est vérifiée que pour le joueur concerné. Les enfants d'un nœud de profondeur 1 sont évalués sur place, sans jouer le coup."),
  p("Mis à part les réductions, ces optimisations ne changent que la vitesse. Nous l'avons vérifié pendant le développement : sans réductions, la recherche renvoie exactement la valeur d'un minimax sans élagage sur 120 couples (position, profondeur).", { before: 40 }),

  h2("1.4 Fonction d'évaluation"),
  formula("valeur = 100 × (d~adv~ − d~moi~) + 124 × (murs~moi~ − murs~adv~) ± 50"),
  p("où d est la longueur du plus court chemin vers le but, en centièmes de pas. Le dernier terme, un demi-pas pour le joueur au trait, rend comparables des feuilles de profondeurs différentes, ce que produisent les réductions. Cette forme, différence des distances plus différence des murs en main, est celle qu'utilise Slatton [1], et ces deux caractéristiques font aussi partie de celles qu'étudie Glendenning [3]."),
  p("Le poids des murs n'a pas été choisi à la main. Nous avons d'abord ajusté une régression logistique sur 6 159 positions de parties, chacune étiquetée par le résultat final (exactitude en validation de 0,829, contre 0,504 pour la classe majoritaire). Les coefficients des deux distances, −25,01 et +24,99, sont presque opposés, ce qui confirme la forme « différence de distances ». Celui des murs, 31,67, donne 1,24 pas par mur en main, alors que nos trois premières versions le comptaient pour 0,08 pas et Slatton [1] pour environ 0,22. Nous avons ensuite vérifié cette valeur par recherche locale [4] : une montée de colline sur le poids, dont la fonction objectif est le score sur 80 parties à profondeur fixe avec ouvertures appariées. Aucune des six valeurs voisines essayées, de 84 à 164, n'a battu 124 de façon reproductible. La seule acceptée, 134 avec 57,5 %, est retombée à 49,4 % sur 160 parties de confirmation."),
  p("Deux termes de la V4 ont été retirés. La mobilité recevait un coefficient négatif dans la régression. La « vulnérabilité » (l'allongement que le meilleur mur adverse peut nous imposer) prenait 69 % du temps de recherche et doublait ce que la recherche explore déjà : appliquée à la racine, elle a fait tomber le score à 28 % (figure 2)."),

  h2("1.5 Gestion des 15 minutes"),
  formula("budget = min( temps utile ÷ coups restants estimés ; plafond ; 20 % du temps utile )"),
  p("Le temps utile est le temps restant moins 3 s de marge pour la latence de communication. Le nombre de coups restants est estimé par max(12, notre distance + nos murs en main). Le plafond vaut 20 s en général, 1 s pendant les quatre premiers demi-coups tant qu'aucun mur n'est posé (l'avance y est forcée), et 0,5 s quand plus personne n'a de mur (une simple course). Le troisième terme fait décroître le budget géométriquement : le temps ne peut pas s'épuiser, quelle que soit la longueur de la partie."),
  p("Dans un coup, le chronomètre démarre à la première ligne de //compute_action// et l'horloge est relue tous les 256 nœuds. Aucune nouvelle passe ne commence après 45 % du budget, car une passe coûte environ " + N.pass_ratio + " fois la précédente. Une passe interrompue n'est pas perdue : elle examine d'abord le meilleur coup de la passe précédente, donc son meilleur coup provisoire est au moins aussi bon. " + N.time_sentence),

  h2("1.6 Garde anti-répétition"),
  p("Revenir sur l'une de nos six dernières cases coûte 0,32 pas divisé par l'ancienneté de la case, et cette pénalité augmente après le 150^e^ demi-coup. Elle ne s'applique qu'à la racine : l'historique de la partie est la seule information que la recherche ne voit pas, et l'introduire dans l'arbre fausserait les valeurs de la table de transposition. La section 2 explique d'où vient cette garde."),
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
      ["V5", "Agent_v5, puis Agent_V5_light", "Moteur de recherche réécrit : variation principale, table indexée par la position, réductions des coups tardifs, distances héritées. Évaluation ramenée à deux termes, poids confirmé par recherche locale."],
    ],
    [10, 24, 66],
  ),
  gap(80),
  p("**V1 → V2 → V3.** La V2 ajoutait cinq mécanismes d'un coup, sans mesure entre chacun. Au budget réel, elle jouait des coups de plusieurs centaines de secondes, et sa table de symétrie reflétait mal les murs verticaux (c → 8 − c au lieu de 9 − c, ce qui confondait 35 positions non équivalentes sur 298). La V3 a fait l'inverse : rendre le temps prévisible et la recherche rapide avant d'ajouter quoi que ce soit. Nous avons trouvé trois causes de dépassement (713 ms de travail avant le démarrage du chronomètre, une formule qui pouvait accorder 225 s à un seul coup, une horloge relue toutes les 38 ms seulement) et ramené le pire dépassement d'un facteur 6,3 à 1,2."),
  p("**V3 → V4.** La V3 cherchait deux fois plus profond (2 → 4 demi-coups) sans gagner plus souvent contre la V1 (10 – 10). Nous en avons conclu que l'évaluation limitait l'agent, et la V4 lui a été consacrée. Sa première soumission a été rejetée par Abyss après une partie de 2 992 demi-coups, sans qu'aucune limite de temps ait cédé (295 s utilisées sur 900, coup le plus long de 15,0 s). Notre pion perdait dans toutes les lignes, et comme une défaite lointaine est mieux notée qu'une défaite proche, faire des allers-retours était le coup le mieux évalué, face à un adversaire qui temporisait aussi. La garde de la section 1.6 corrige ce comportement : rejouée depuis la vraie position finale, la V4 d'origine visite 2 cases en 250 coups, alors que la version corrigée termine en 100 demi-coups."),
  p("**V4 → V5.** Sur Abyss, la V4 n'a gagné que 12 de ses 30 premières parties. Leur analyse (section 3.3) montre que les adversaires gagnent avec des barrières de plusieurs murs, hors de portée d'une recherche à 4 ou 5 demi-coups. Deux options s'offraient à nous : enrichir l'évaluation pour estimer ces barrières, ou chercher plus profond. Un prototype de la première (potentiel multi-murs, évaluation par simulation de fin de partie) a perdu 2 – 4 puis 0 – 4 contre la V4. À l'inverse, la V4 avec 6 s par coup battait environ deux fois sur trois la V4 limitée à 0,4 s. La V5 mise donc sur la profondeur."),
];

const results = [
  h1("3. Résultats"),
  p("Nous évaluons l'agent selon quatre critères. Le nombre de positions visitées pour terminer une profondeur mesure l'efficacité de l'élagage. Les matchs se jouent avec couleurs alternées et ouvertures appariées, et leur score est donné avec un intervalle de confiance de Wilson à 95 %. Nous mesurons aussi la proportion de positions où deux versions choisissent des coups différents et, dans les parties exportées d'Abyss, l'évolution des distances au but. Ces mesures proviennent de scripts de développement qui ne font pas partie de la remise."),

  h2("3.1 Efficacité de l'élagage"),
  figure("fig_pruning.png", 640, N.fig_pruning_ratio),
  caption("**Figure 1.** Positions visitées pour terminer chaque profondeur, moyenne géométrique sur " + N.positions + " positions tirées de parties de l'agent contre lui-même. Pour les trois variantes de recherche, le compte cumule toutes les passes de l'approfondissement itératif."),
  p(N.pruning_text),

  h2("3.2 Matchs entre versions"),
  p("La figure 2 rassemble les matchs réalisés. Trois enseignements s'en dégagent. **Mesurer coûte cher.** Avec 36 parties, l'intervalle couvre environ ±16 points : ni la vulnérabilité (47 %) ni le poids des murs seul (56 %) ne se distinguent du hasard. C'est leur combinaison, testée sur 51 parties, qui a justifié la V4. **Beaucoup d'idées plausibles échouent.** L'évaluation exacte des fins de partie ne changeait aucune décision (0 position sur 65), le comptage de chemins nuit à deux calibrages différents (57/136) et la vulnérabilité à la racine est le seul résultat nettement négatif. Compter les décisions qui changent prend une minute, contre trente pour un match ; ce filtre nous a évité plusieurs matchs inutiles. **La V5 est le seul gain net** : " + N.v5_sentence),
  figure("fig_matches.png", 640, N.fig_matches_ratio),
  caption("**Figure 2.** Score de chaque variante contre la version indiquée (une partie nulle compte pour un demi-point). Budgets par agent et par partie : de 10 à 900 s selon le match, identiques pour les deux joueurs."),
  p("La détection de symétrie est correcte et ne coûte rien, mais elle n'apporte presque rien en jeu (15 – 15, taille de table identique à 0,1 % près). Une position et son miroir ne se croisent dans le même arbre que tant que le plateau reste symétrique, c'est-à-dire pendant les premiers coups. Le gain d'un facteur 2 rapporté par Slatton [1] concerne un solveur qui énumère toutes les configurations de murs, un cadre différent du nôtre."),

  h2("3.3 Parties sur Abyss"),
  caption("**Tableau 2.** Bilan sur Abyss au 24 novembre 2026.", { keepNext: true, before: 0, after: 60 }),
  table(
    ["Agent", "Version", "Victoires – défaites", "Victoires", "Elo"],
    [
      ["Agent1", "V1", "372 – 362", "50,7 %", "815"],
      ["Agent_V2", "V2", "372 – 345", "51,9 %", "1183"],
      ["v3_agent", "V3 (avant correctif de temps)", "489 – 465", "51,3 %", "1030"],
      ["AgentFastboard_V3", "V3", "178 – 157", "53,1 %", "1273"],
      ["Agent_V4_fixed", "V4 corrigée", "110 – 100", "52,4 %", "1083"],
      ["Agent_v5", "V5", "93 – 80", "53,8 %", "1158"],
      ["Agent_V5_light", "V5 (seconde soumission)", "72 – 59", "55,0 %", "1134"],
    ],
    [26, 28, 18, 13, 15],
  ),
  gap(80),
  p("Ces résultats en ligne nuancent ceux obtenus lors de nos matchs locaux. Le taux de victoire passe de 50,7 % (V1) à 54,3 % pour les deux V5 réunies (165 – 139), une progression beaucoup plus modeste que ne le laissaient prévoir nos essais. Les Elo ne se comparent toutefois pas directement entre versions : chaque agent a affronté les adversaires présents pendant sa propre période d'activité. L'Elo plus élevé d'AgentFastboard_V3 ne signifie donc pas qu'il est plus fort que les V5."),
  p("Les parties exportées nous ont appris davantage que nos matchs locaux. Avant la V4, nos neuf défaites analysées suivent le même scénario : notre pion arrive à 1 à 5 pas du but par un seul chemin, puis l'adversaire l'enferme et la distance remonte à 8 – 26 pas. Dans les 30 premières parties de la V4, tout se joue encore sur l'enfermement, et le décompte des murs explique pourquoi. Le premier mur d'un joueur rapporte en moyenne 1,0 pas net, les murs 6 à 10 entre 2,5 et 3,1 pas : les murs ont des rendements croissants, parce qu'une barrière ne devient coûteuse à contourner qu'une fois presque fermée. Nos adversaires posent en moyenne 9,5 murs par partie, le premier vers le 9^e^ demi-coup. La V4 en posait 7,8, le premier vers le 13^e^, et finissait 11 de ses 18 défaites avec des murs inutilisés. Cela rejoint une observation du projet Quoridor-AI [2] : les agents forts posent d'abord des murs pour contraindre l'adversaire, puis courent vers leur but. Comme un mur en main vaut 1,24 pas dans notre évaluation, plus que le gain d'un premier mur, seule une recherche qui voit le troisième ou le quatrième mur peut justifier de commencer une barrière."),
];

const discussion = [
  h1("4. Discussion"),
  p("**Avantages.** L'agent final présente trois atouts principaux. Il est rapide : " + N.depth_sentence + " Il est fiable : pendant le développement, nous avons établi que le plateau respecte les règles du moteur et que la recherche renvoie la valeur minimax, ce qui nous a permis de réécrire le moteur en V5 sans régression cachée ; son temps de calcul est borné par construction et il ne peut pas rendre d'action illégale. Enfin, il est sobre : sa fonction d'évaluation ne comporte que trois constantes, toutes déterminées à partir de mesures."),
  p("**Limites.** (1) L'effet d'horizon demeure : une barrière de quatre ou cinq murs dépasse encore la profondeur atteinte en début de partie, et le filtre des murs candidats écarte ceux qui ne font que préparer une barrière. Sur 72 positions de début de parties perdues sur Abyss, la V5 choisit un mur 19 fois, contre 23 pour la V4 : elle calcule mieux, mais n'entre pas plus tôt dans la guerre de murs. (2) Les gains locaux se transfèrent mal. La V5 battait la V4 10 – 2 en local, mais ne gagne en ligne que 54,3 % de ses parties, contre 52,4 % pour la V4. Battre nos propres versions ne garantit donc pas de battre des adversaires qui jouent autrement. (3) Le poids des murs est un optimum mesuré contre l'agent lui-même, à profondeur fixe. " + N.limit_sentence),
  p("**Pistes d'amélioration.** La priorité est d'étendre la recherche le long des séquences de murs forcées, afin de suivre une barrière jusqu'à sa fermeture plutôt que de s'arrêter à profondeur fixe. On pourrait ensuite ajouter un terme d'évaluation qui estime le coût de fermeture d'une barrière entamée, à condition qu'il reste assez rapide pour ne pas répéter l'échec de la vulnérabilité. D'autres pistes sont l'ajustement des poids à partir de parties d'Abyss plutôt que de parties contre nous-mêmes et la création hors ligne d'un petit livre d'ouvertures, qui rendrait enfin la détection de symétrie utile. La V5 améliore nettement l'efficacité de la recherche et la fiabilité de l'agent, mais les résultats sur Abyss montrent que sa principale limite demeure l'anticipation des barrières adverses."),
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
