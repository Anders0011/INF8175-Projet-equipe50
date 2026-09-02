//wait for document to be ready
$(document).ready(function() {

    // Screen orientation handling for mobile/tablet devices
    function handleOrientationChange() {
        // Small delay to ensure orientation change is complete
        setTimeout(function() {
            // Check if we're on a mobile/tablet device
            if (window.innerWidth <= 1024) {
                adjustCanvasSize();
                // Force redraw of the canvas to handle size changes
                if (steps.length > 0 && index >= 0) {
                    drawNewState(steps[index]);
                } else {
                    drawGrid({});
                }
            }
        }, 100);
    }

    // Listen for orientation changes
    window.addEventListener('orientationchange', handleOrientationChange);
    window.addEventListener('resize', handleOrientationChange);

    /* Board representation */
    const canvasBoard = document.getElementById("board");
    const ctxBoard = canvasBoard.getContext("2d");
    const gridSize = 9;
    const boardPath = './assets/quoridor_board.png';
    const offsetX = canvasBoard.width*0.1045; // horizontal distance between two centers
    const offsetY = canvasBoard.height*0.1045; // vertical distance between two centers
    const cellWidth = offsetX*0.42; // width of the cell
    const cellSize = offsetY*0.42; // height of the cell
    const spaceXSize = offsetX*0.16; // width of the vertical space between two cell
    const spaceYSize = offsetY*0.16; // height of the horizontal space between two cell
    const initialX = canvasBoard.width*0.0828;
    const initialY = canvasBoard.height*0.0828;


    // Load the piece images
    const pieceImages = {};
    // const pieceTypes = ['R', 'B'];
    const pieceColors = ['W','B'];
    // const playerColor = ['W', 'B'];
    for (const color of pieceColors) {
        const pieceImg = new Image();
        pieceImg.src = `./assets/${color}.png`;
        pieceImages[color] = pieceImg;
    }

    const cellCoordinates = {};
    for (let row = 0; row < gridSize; row++) {
        for (let col = 0; col < gridSize; col++) {
            const cellCenterCoordinates = getCellCoordinates(row, col);
            cellCoordinates[`${row},${col}`] = cellCenterCoordinates;
        }
    }
    const firstPlayersData = {
        "W": {
            "name": "Player 1",
            "score": 0,
            "id": 1,
        },
        "B": {
            "name": "Player 2",
            "score": 0,
            "id": 2,
        }
            
    };

    // Load and draw the background board
    const boardImg = new Image();
    boardImg.src = boardPath;

    const wallVImage = new Image();
    wallVImage.src = './assets/wall_vertical.png';

    const wallHImage = new Image();
    wallHImage.src = './assets/wall_horizontal.png';
    
    // wait for the image to be loaded before proceeding
    boardImg.onload = function() {
        adjustCanvasSize();
        drawGrid({});
        // Initialiser l'affichage des joueurs
        // Définir les noms initiaux par défaut
        window.initialPlayerNames = {
            player1: "Player 1",
            player2: "Player 2"
        };
        updatePlayerDisplay(firstPlayersData, "Player 1", { 1: 10, 2: 10 });
    }

    // Function to adjust canvas size based on screen size
    function adjustCanvasSize() {
        // Detect smartphone by screen dimensions (works in any orientation)
        const isSmartphone = (window.innerWidth <= 600) || 
                           (window.innerHeight <= 600 && window.innerWidth <= 900);
        
        if (isSmartphone) {
            // Smartphone: side-by-side layout with board and stacked players
            const availableWidth = Math.min(window.innerWidth * 0.7, window.innerWidth - 100);
            const availableHeight = Math.min(window.innerHeight * 0.6, window.innerHeight - 150);
            
            // Maintain aspect ratio (600:600)
            const aspectRatio = 600 / 600;
            let newWidth, newHeight;
            
            if (availableWidth / aspectRatio <= availableHeight) {
                newWidth = availableWidth;
                newHeight = availableWidth / aspectRatio;
            } else {
                newHeight = availableHeight;
                newWidth = availableHeight * aspectRatio;
            }
            
            // Ensure minimum size for smartphone playability
            const minWidth = Math.min(250, window.innerWidth * 0.6);
            const minHeight = minWidth / aspectRatio;
            
            newWidth = Math.max(newWidth, minWidth);
            newHeight = Math.max(newHeight, minHeight);
            
            canvasBoard.style.width = newWidth + 'px';
            canvasBoard.style.height = newHeight + 'px';
            canvasBoard.style.display = 'block';
            
        } else if (window.innerWidth <= 1024) {
            // Tablet: board above player panels
            const containerWidth = Math.min(window.innerWidth * 0.95, window.innerWidth - 20);
            const containerHeight = Math.min(window.innerHeight * 0.5, window.innerHeight - 200);
            
            // Maintain aspect ratio (600:600)
            const aspectRatio = 600 / 600;
            let newWidth, newHeight;
            
            if (containerWidth / aspectRatio <= containerHeight) {
                newWidth = containerWidth;
                newHeight = containerWidth / aspectRatio;
            } else {
                newHeight = containerHeight;
                newWidth = containerHeight * aspectRatio;
            }
            
            // Ensure minimum size for tablet playability
            const minWidth = Math.min(400, window.innerWidth * 0.8);
            const minHeight = minWidth / aspectRatio;
            
            newWidth = Math.max(newWidth, minWidth);
            newHeight = Math.max(newHeight, minHeight);
            
            canvasBoard.style.width = newWidth + 'px';
            canvasBoard.style.height = newHeight + 'px';
            canvasBoard.style.display = 'block';
            
        } else {
            // PC: keep original size
            canvasBoard.style.width = '600px';
            canvasBoard.style.height = '600px';
            canvasBoard.style.display = 'block';
        }
    }

    var steps = [];
    var index = -1;
    var play = false;
    var lastCellMouseOn = null;
    var lastPieceMouseOn = null;
    var active_player;
    var loop = null;
    var playersName = {
        "W": "Player 1",
        "B": "Player 2"
    };
    var socket = io({
        reconnection: false,
    });
    
    canvasBoard.addEventListener('mousemove', function(event) {
        const rect = canvasBoard.getBoundingClientRect();
        const scaleX = canvasBoard.width / rect.width;
        const scaleY = canvasBoard.height / rect.height;
        const mouseX = (event.clientX - rect.left) * scaleX;
        const mouseY = (event.clientY - rect.top) * scaleY;
        handleMouseMove(mouseX, mouseY);
    });

    //dbl click to avoid accidental clicks
    canvasBoard.addEventListener('dblclick', function(event) {
        const rect = canvasBoard.getBoundingClientRect();
        const scaleX = canvasBoard.width / rect.width;
        const scaleY = canvasBoard.height / rect.height;
        const mouseX = (event.clientX - rect.left) * scaleX;
        const mouseY = (event.clientY - rect.top) * scaleY;
        handleMouseClickBoard(mouseX, mouseY);
    });

    // Touch events for mobile devices
    let touchStartTime = 0;
    let touchStartPos = { x: 0, y: 0 };
    
    canvasBoard.addEventListener('touchstart', function(event) {
        event.preventDefault();
        touchStartTime = Date.now();
        const touch = event.touches[0];
        const rect = canvasBoard.getBoundingClientRect();
        touchStartPos.x = touch.clientX - rect.left;
        touchStartPos.y = touch.clientY - rect.top;
    });

    canvasBoard.addEventListener('touchend', function(event) {
        event.preventDefault();
        const touchDuration = Date.now() - touchStartTime;
        const touch = event.changedTouches[0];
        const rect = canvasBoard.getBoundingClientRect();
        const touchEndX = touch.clientX - rect.left;
        const touchEndY = touch.clientY - rect.top;
        
        // Check if it's a tap (not a drag) and duration is reasonable
        const distance = Math.sqrt(
            Math.pow(touchEndX - touchStartPos.x, 2) + 
            Math.pow(touchEndY - touchStartPos.y, 2)
        );
        
        if (touchDuration < 500 && distance < 20) {
            const scaleX = canvasBoard.width / rect.width;
            const scaleY = canvasBoard.height / rect.height;
            const mouseX = touchEndX * scaleX;
            const mouseY = touchEndY * scaleY;
            handleMouseClickBoard(mouseX, mouseY);
        }
    });

    canvasBoard.addEventListener('touchmove', function(event) {
        event.preventDefault();
        const touch = event.touches[0];
        const rect = canvasBoard.getBoundingClientRect();
        const scaleX = canvasBoard.width / rect.width;
        const scaleY = canvasBoard.height / rect.height;
        const mouseX = (touch.clientX - rect.left) * scaleX;
        const mouseY = (touch.clientY - rect.top) * scaleY;
        handleMouseMove(mouseX, mouseY);
    });

    function handleMouseClickBoard(mouseX, mouseY) {
        const cell = isMouseOnCell(mouseX, mouseY);
        console.log(cell);
        if (cell !== null) {
            socket.emit("interact", JSON.stringify({
                "type": cell[0],
                "destination": [cell[1], cell[2]]
            }));
            selectedPiece = null;
            lastPieceMouseOn = null;
            lastCellMouseOn = null;
        }
    }

    function handleMouseMove(mouseX, mouseY) {
        const cell = isMouseOnCell(mouseX, mouseY);
        if (cell !== null && (lastCellMouseOn === null || cell.toString() !== lastCellMouseOn.toString())) {
            canvasBoard.style.cursor = "pointer";
            ctxBoard.clearRect(0, 0, canvasBoard.width, canvasBoard.height);
            drawGrid(steps[index] ? steps[index] : null);
            if (cell[0] === 'move') {
                placeHighlightedCell(cell[1], cell[2]);
            }else if (cell[0] === 'vertical' ){
                placeHighlightedVertical(cell[1], cell[2]);
            }else{
                placeHighlightedHorizontal(cell[1], cell[2]);
            }
            lastCellMouseOn = cell;
        }else if(cell === null){
            canvasBoard.style.cursor = "default";
            ctxBoard.clearRect(0, 0, canvasBoard.width, canvasBoard.height);
            //Redraw to erase the piece background
            drawGrid(steps[index] ? steps[index] : null);
        }
    }
    
    function placeHighlightedCell(row, col) {
        const cellCenter = getCellCoordinates(row, col);
        ctxBoard.save();
        ctxBoard.beginPath();
        ctxBoard.ellipse(cellCenter.x, cellCenter.y, cellWidth*0.9, cellSize*0.9, 0, 0, 2 * Math.PI);
        ctxBoard.strokeStyle = "#39ff14";
        ctxBoard.lineWidth = 2;
        ctxBoard.stroke();
        ctxBoard.restore();
    }

    function placeHighlightedVertical(row, col) {
        const cellCenter = getCellCoordinates(row, col - 1);
        ctxBoard.save();
        ctxBoard.strokeStyle = "#39ff14";
        ctxBoard.lineWidth = 2;
        ctxBoard.strokeRect(cellCenter.x+offsetX*0.42, cellCenter.y-offsetY*0.40, spaceXSize, offsetY*0.80 + spaceYSize + 2*cellSize);
        ctxBoard.restore();
    }

    function placeHighlightedHorizontal(row, col) {
        const cellCenter = getCellCoordinates(row - 1, col);
        ctxBoard.save();
        ctxBoard.strokeStyle = "#39ff14";
        ctxBoard.lineWidth = 2;
        ctxBoard.strokeRect(cellCenter.x-offsetX*0.40, cellCenter.y+offsetY*0.42, offsetX*0.80 + spaceXSize + 2*cellWidth, spaceYSize);
        ctxBoard.restore();
    }

    function isMouseOnCell(mouseX, mouseY){
        // Debug logging for mobile devices
        if (window.innerWidth <= 1024) {
            console.log(`Mouse coordinates: (${mouseX.toFixed(2)}, ${mouseY.toFixed(2)})`);
            console.log(`Canvas actual size: ${canvasBoard.width}x${canvasBoard.height}`);
            console.log(`Canvas display size: ${canvasBoard.offsetWidth}x${canvasBoard.offsetHeight}`);
        }
        
        //Compute the cell it belongs
        const colF = (mouseX - initialX - spaceXSize/2.0) / offsetX;
        const rowF = (mouseY - initialY - spaceYSize/2.0) / offsetY;
        
        const col = Math.round(colF);
        const row = Math.round(rowF);
        //determine if the mouse is in a cell, or in the space between cells
        const cellCenterX = initialX + col * offsetX;
        const cellCenterY = initialY + row * offsetY;

        // If the mouse is between 4 cells, return null
        if (Math.abs(mouseX - cellCenterX) > cellWidth && Math.abs(mouseY - cellCenterY) > cellSize) {
            return null;
        }
        let return_value = null;
        //Vertical intercell space check
        if (Math.abs(mouseX - cellCenterX) > cellWidth) {
            return_value = ['vertical', row, col + 1];
        }
        //Horizontal intercell space check
        else if (Math.abs(mouseY - cellCenterY) > cellSize) {
            return_value = ['horizontal', row + 1, col];
        }
        else{
            return_value = ['move', row, col];
        }

        // Debug logging for mobile devices
        if (window.innerWidth <= 1024) {
            if (return_value) {
                console.log(`Calculated cell: (${return_value[0]}, ${return_value[1]}, ${return_value[2]})`);
            }
        }

        if (return_value[1] < 0 || return_value[1] >= gridSize || return_value[2] < 0 || return_value[2] >= gridSize) {
            return null;
        }
        return return_value;
    }

    
    $("#loadJson").on("change", function() {
        const file = this.files[0];
        const reader = new FileReader();
        reader.onload = function(e) {
            const json = JSON.parse(e.target.result);
            let gameData = [];

            for (const step of json) {
                const players_info = convertToPlayerInfo(step.players, step.scores);
                gameData.push({"pawn_positions": step.rep.pawn_positions, "walls": step.rep.walls, "remaining_walls": step.rep.remaining_walls, "players":players_info, "active_player": step.active_player.name});
            }
            steps = gameData;
            index = 0;
            drawNewState(steps[index]);
        }
        reader.readAsText(file);
    });


    $('#time').on('change', function() {
        play = false;
        $("#play").click();
    });

    $("#play").click(function() {
        play = true;
        
        if (loop) {
            clearInterval(loop);
        }
        
        loop = setInterval(function() {
            if (play) {
                if (index < steps.length - 1) {
                    index++;
                    drawNewState(steps[index]);
                } else {
                    play = false;
                    clearInterval(loop);
                }
            } else {
                clearInterval(loop);
            }
        }, $("#time").attr("max") - $("#time").val());
    });

    $("#stop").click(function() {
        play = false;
    });

    $("#reset").click(function() {
        index = 0;
        drawNewState(steps[index]);
    });
    $("#next").click(function() {
        if (index < steps.length - 1) {
            index++;
            drawNewState(steps[index]);
        }
    });

    $("#previous").click(function() {
        if (index > 0) {
            index--;
            drawNewState(steps[index]);
        }
    });
    $("#close_pop_up").click(function() {
        $("#pop_up_container").css("display", "none");

    });
    connect_handler = () => {
        socket = io("ws://" + $("#hostname")[0].value + ":" + $("#port")[0].value + "", {
            reconnection: false,
        });

        socket.on("connect_error", (err) => {
            $("#connect").addClass("connection_error");

        });

        socket.on("connect", () => {
            $("#connect").removeClass("connection_error");
            socket.emit("identify", JSON.stringify({
                "identifier": "__GUI__" + Date.now()
            }));
            $("#status")[0].innerHTML = 'Connected';
            $("#status")[0].style = 'color:green';
            $("#connect").unbind();
            $('#loadJsonButton').addClass('disabled');
            
        });

        socket.on("play", (...args) => {
            json = JSON.parse(args[0]);
            if (!json.rep) json = JSON.parse(json);
            if (json.rep && json.rep.pawn_positions && json.rep.walls && json.rep.remaining_walls) {
                nextPlayer = json.active_player.name;
                const players_info = convertToPlayerInfo(json.players, json.scores);
                steps.push({"pawn_positions": json.rep.pawn_positions, "walls": json.rep.walls, "remaining_walls": json.rep.remaining_walls, "players":players_info, "active_player": nextPlayer});
                index = steps.length - 1;
                drawNewState(steps[index]);
            }
        });

        socket.on("ActionNotPermitted", (...args) => {
            // TODO: Display message to user
            $("#error").css("opacity", "1");
            setTimeout(function() {
                $("#error").css("opacity", "0");
            }, 2000);
            selectedPiece = null;
        })

        socket.on("disconnect", (...args) => {
            // set display block to img of id #img
            $("#status")[0].innerHTML = 'Disconnected';
            $("#status")[0].style = 'color:red';
            $("#connect").click(connect_handler);
            $('#loadJsonButton').removeClass('disabled');
        });

        socket.on("done", (...args) => {
            score = JSON.parse(args[0])
            winner_id = score["winners_id"][0]
            winner_name = ""
            winner_color = ""
            for (p in steps[steps.length - 1].players) {
                if (steps[steps.length - 1].players[p].id == winner_id) {
                    winner_name = steps[steps.length - 1].players[p].name
                    winner_color = p
                }
            }
            const nstep = score["custom_stats"][0].value;
            text = "Le joueur " + winner_name + " (<span class=\"winner_indicator " + winner_color + "\"></span>) est vainqueur apres "+ nstep + " coups !"
            $("#pop_up_container").css("display", "flex");
            $("#pop_up_text").html(text);

        })

    }

    $("#connect").click(connect_handler);
    connect_handler();

    function drawCoordinates() {

        ctxBoard.save();
        ctxBoard.font = "bold 18px Arial";
        ctxBoard.fillStyle = "#FFFFFF";
        ctxBoard.textAlign = "center";
        ctxBoard.textBaseline = "middle";

        for (let col = 0; col < gridSize; col++) {
            const coord = getCellCoordinates(0, col);
            // ctxBoard.fillText((col).toString(), coord.x - 2, initialY - offsetY * 0.45);}
            ctxBoard.fillText(String.fromCharCode(97 + col), coord.x, initialY - offsetY * 0.45);}

        for (let row = 0; row < gridSize; row++) {
            const coord = getCellCoordinates(row, 0);
            // ctxBoard.fillText((row).toString(), initialX - offsetX * 0.45, coord.y);}
            ctxBoard.fillText((row + 1).toString(), initialX - offsetX * 0.45, coord.y);}

        ctxBoard.restore();
    }

    function drawNewState(newState) {
        if (newState === undefined){
            newState = {"pawn_positions": {}, "walls": [], "remaining_walls": {}, "players": firstPlayersData, "active_player": "Player 1"};
            console.log("No state provided, drawing initial state.");
        }
        active_player = newState.active_player;
        drawGrid(newState);
        updatePlayerDisplay(newState.players, active_player, newState.remaining_walls);
    }

    function convertToPlayerInfo(players, scores){
        let playerInfo = {};
        for (let player of players) {
            let playerColor = player.piece_type;
            playerInfo[playerColor] = {
                "name": player.name,
                "score": scores[player.id],
                "id": player.id,
            }
            playersName[playerColor] = player.name;
        }
        return playerInfo;
    }
    
    function drawGrid(rep) {
        console.log(rep)
        ctxBoard.clearRect(0, 0, canvasBoard.width, canvasBoard.height);
        ctxBoard.drawImage(boardImg, 0, 0, canvasBoard.width, canvasBoard.height);
        drawCoordinates();

        if (rep === undefined || rep === null) {
            return;
        }
        const player1Id = rep.players['W'] ? rep.players['W'].id : null;
        const player2Id = rep.players['B'] ? rep.players['B'].id : null;

        //check if the rep has pawn_positions 
        if (rep.pawn_positions && player1Id) {

            player1Pos = rep.pawn_positions[player1Id];
            player2Pos = rep.pawn_positions[player2Id];

            placePiece(player1Pos[0], player1Pos[1], pieceImages['W']);
            placePiece(player2Pos[0], player2Pos[1], pieceImages['B']);
        }

        if (rep.walls && player1Id) {
            //iterate over the walls and draw them
            for (const wall of rep.walls) {
                if (wall.orientation ==="V") {
                    const centerX = initialX + (wall['col']-1)*offsetX + cellWidth;
                    const centerY = initialY + wall['row']*offsetY - cellSize ;
                    ctxBoard.drawImage(wallVImage, centerX, centerY, spaceXSize, 4*cellSize + spaceYSize);
                }
                else if (wall.orientation ==="H") {
                    const centerX = initialX + wall['col']*offsetX - cellWidth;
                    const centerY = initialY + (wall['row']-1)*offsetY + cellSize;
                    ctxBoard.drawImage(wallHImage, centerX, centerY, 4*cellWidth + spaceXSize, spaceYSize);
                }else{
                    console.log("Unknown wall orientation: " + wall.orientation);
                }
            }
            updatePlayerDisplay(rep.players, rep.active_player, rep.remaining_walls);
        }
    }

    

    function placePiece(row, col, pieceImg) {
        if (!pieceImg.complete || pieceImg.naturalWidth === 0) {
            pieceImg.onload = function() {
                drawPiece(getCellCoordinates(row, col), ctxBoard, pieceImg);
            };
        } else {
            drawPiece(getCellCoordinates(row, col),ctxBoard, pieceImg);
        }
    }
    
    function drawPiece(coord, ctx, pieceImg, rotate = false) {
        ctx.drawImage(pieceImg, coord.x - cellWidth, coord.y - cellSize, 2*cellWidth, 2*cellSize);
    }

    function getCellCoordinates(row, col) {
        const x = initialX + col * offsetX;
        const y = initialY + row * offsetY;
        return { x: x, y: y };
    }

    function drawPoint(x, y) {
        ctxBoard.beginPath();
        ctxBoard.arc(x, y, 10, 2, 2 * Math.PI);
        ctxBoard.fillStyle = 'red';
        ctxBoard.fill();
        ctxBoard.closePath();
    }

    function updatePlayerDisplay(players, currentPlayer, remainingWalls) {
        // Récupérer les informations des joueurs
        const player1Info = document.getElementById('player1Info');
        const player1Name = player1Info.querySelector('.player-name');
        const player1Piece = player1Info.querySelector('.player-piece');
        const player1WallsCount = player1Info.querySelector('.player-walls-count');
        
        const player2Info = document.getElementById('player2Info');
        const player2Name = player2Info.querySelector('.player-name');
        const player2Piece = player2Info.querySelector('.player-piece');
        const player2WallsCount = player2Info.querySelector('.player-walls-count');

        const getRemainingWalls = function(playerId) {
            if (remainingWalls !== undefined && Object.prototype.hasOwnProperty.call(remainingWalls, playerId)) {
                return Number(remainingWalls[playerId]);
            }
            return 10;
        };
        
        // Initialiser les noms des joueurs fixes s'ils n'existent pas encore
        if (!window.initialPlayerNames) {
            window.initialPlayerNames = {};
            if (players && players['W']) {
                window.initialPlayerNames.player1 = players['W'].name;
            }
            if (players && players['B']) {
                window.initialPlayerNames.player2 = players['B'].name;
            }
        }
        
        if (players && players['W'] && players['B']) {
            player1Data = { name: players['W'].name, color: 'W', id: players['W'].id };
            player2Data = { name: players['B'].name, color: 'B', id: players['B'].id };
            
            // Mettre à jour l'affichage du joueur 1
            player1Name.textContent = player1Data.name;
            player1Piece.className = `player-piece ${player1Data.color}`;
            player1WallsCount.textContent = getRemainingWalls(player1Data.id);
            
            // Mettre à jour l'affichage du joueur 2
            player2Name.textContent = player2Data.name;
            player2Piece.className = `player-piece ${player2Data.color}`;
            player2WallsCount.textContent = getRemainingWalls(player2Data.id);
            
            // Gérer la classe active selon le joueur actuel
            if (currentPlayer === player1Data.name) {
                player1Info.classList.add('active');
                player2Info.classList.remove('active');
            } else if (currentPlayer === player2Data.name) {
                player2Info.classList.add('active');
                player1Info.classList.remove('active');
            } else {
                player1Info.classList.remove('active');
                player2Info.classList.remove('active');
            }
        }
    }
});