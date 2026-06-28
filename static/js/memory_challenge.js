(function () {
    const configEl = document.getElementById("memory-challenge-config");
    if (!configEl) {
        return;
    }

    const config = JSON.parse(configEl.textContent);
    const originalMemoryCards = config.cards || [];
    const memoryDifficulty = config.difficulty || "easy";
    const memoryPairCount = Number(config.pairCount) || 0;
    const completionUrl = config.completionUrl;
    const baseXp = Number(config.baseXp) || 0;

    let memoryCards = [];
    let openCards = [];
    let lockBoard = false;
    let moves = 0;
    let matchedPairs = 0;
    let combo = 0;
    let bestCombo = 0;
    let startedAt = null;
    let timerId = null;
    let muted = false;
    let focusedIndex = 0;

    const boardEl = document.getElementById("memory-board");
    const timerEl = document.getElementById("memory-timer");
    const movesEl = document.getElementById("memory-moves");
    const accuracyEl = document.getElementById("memory-accuracy");
    const remainingEl = document.getElementById("memory-remaining");
    const comboEl = document.getElementById("memory-combo");
    const xpEl = document.getElementById("memory-xp");
    const progressEl = document.getElementById("memory-progress-bar");
    const modalEl = document.getElementById("memory-completion");

    function formatTime(seconds) {
        const safeSeconds = Math.max(0, Number(seconds) || 0);
        const minutes = Math.floor(safeSeconds / 60);
        return `${minutes}:${String(safeSeconds % 60).padStart(2, "0")}`;
    }

    function elapsedSeconds() {
        if (!startedAt) {
            return 0;
        }
        return Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
    }

    function shuffleCards(cards) {
        const shuffled = cards.slice();
        for (let index = shuffled.length - 1; index > 0; index -= 1) {
            const swapIndex = Math.floor(Math.random() * (index + 1));
            [shuffled[index], shuffled[swapIndex]] = [shuffled[swapIndex], shuffled[index]];
        }
        return shuffled;
    }

    function startTimer() {
        if (timerId) {
            return;
        }
        startedAt = Date.now();
        timerId = window.setInterval(() => {
            timerEl.textContent = formatTime(elapsedSeconds());
        }, 250);
    }

    function stopTimer() {
        if (timerId) {
            window.clearInterval(timerId);
            timerId = null;
        }
        timerEl.textContent = formatTime(elapsedSeconds());
    }

    function currentAccuracy() {
        if (!moves) {
            return 100;
        }
        return Math.round((matchedPairs / moves) * 1000) / 10;
    }

    function currentXp() {
        const comboBonus = Math.max(0, bestCombo - 1) * 2;
        const perfectBonus = matchedPairs === memoryPairCount && currentAccuracy() >= 100 ? 10 : 0;
        return baseXp + comboBonus + perfectBonus;
    }

    function playTone(type) {
        if (muted || !window.AudioContext && !window.webkitAudioContext) {
            return;
        }
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        const context = new AudioContextClass();
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        const toneMap = {
            match: 660,
            wrong: 180,
            complete: 880
        };
        oscillator.frequency.value = toneMap[type] || 440;
        oscillator.type = type === "wrong" ? "sawtooth" : "sine";
        gain.gain.setValueAtTime(0.05, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.18);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.start();
        oscillator.stop(context.currentTime + 0.2);
    }

    function renderStats() {
        movesEl.textContent = moves;
        accuracyEl.textContent = `${currentAccuracy()}%`;
        remainingEl.textContent = memoryPairCount - matchedPairs;
        comboEl.textContent = combo;
        xpEl.textContent = `+${currentXp()}`;
        progressEl.style.width = `${Math.round((matchedPairs / memoryPairCount) * 100)}%`;
    }

    function renderBoard() {
        boardEl.innerHTML = "";
        boardEl.style.setProperty("--memory-card-count", memoryCards.length);
        memoryCards.forEach((card, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "memory-card";
            button.dataset.cardId = card.id;
            button.dataset.index = index;
            button.setAttribute("aria-label", `${card.label} memory card`);
            button.setAttribute("aria-pressed", "false");
            button.innerHTML = `
                <span class="memory-card-inner">
                    <span class="memory-card-face memory-card-back" aria-hidden="true">
                        <span class="memory-card-icon">AI</span>
                    </span>
                    <span class="memory-card-face memory-card-front">
                        <small>${card.label}</small>
                        <strong></strong>
                    </span>
                </span>
            `;
            button.querySelector("strong").textContent = card.text;
            button.addEventListener("click", () => flipMemoryCard(card.id));
            boardEl.appendChild(button);
        });
        updateFocus();
    }

    function cardElement(cardId) {
        return boardEl.querySelector(`[data-card-id="${cardId}"]`);
    }

    function updateFocus() {
        const cards = Array.from(boardEl.querySelectorAll(".memory-card"));
        cards.forEach((card, index) => {
            card.tabIndex = index === focusedIndex ? 0 : -1;
        });
        if (cards[focusedIndex]) {
            cards[focusedIndex].focus({preventScroll: true});
        }
    }

    function focusByOffset(offset) {
        const cards = Array.from(boardEl.querySelectorAll(".memory-card:not(.matched)"));
        if (!cards.length) {
            return;
        }
        const activeCard = document.activeElement && document.activeElement.classList.contains("memory-card")
            ? document.activeElement
            : cards[0];
        const activeOpenIndex = Math.max(0, cards.indexOf(activeCard));
        const nextCard = cards[(activeOpenIndex + offset + cards.length) % cards.length];
        focusedIndex = Number(nextCard.dataset.index) || 0;
        updateFocus();
    }

    function flipMemoryCard(cardId) {
        if (lockBoard) {
            return;
        }
        const card = memoryCards.find(item => item.id === cardId);
        const element = cardElement(cardId);
        if (!card || !element || card.matched || card.flipped) {
            return;
        }
        startTimer();
        card.flipped = true;
        element.classList.add("flipped");
        element.setAttribute("aria-pressed", "true");
        openCards.push(card);
        if (openCards.length === 2) {
            resolveOpenCards();
        }
    }

    function resolveOpenCards() {
        lockBoard = true;
        moves += 1;
        const [first, second] = openCards;
        const isMatch = first.pairId === second.pairId && first.kind !== second.kind;
        if (isMatch) {
            matchedPairs += 1;
            combo += 1;
            bestCombo = Math.max(bestCombo, combo);
            first.matched = true;
            second.matched = true;
            cardElement(first.id).classList.add("matched", "match-glow");
            cardElement(second.id).classList.add("matched", "match-glow");
            openCards = [];
            lockBoard = false;
            playTone("match");
            renderStats();
            if (matchedPairs === memoryPairCount) {
                window.setTimeout(completeGame, 450);
            }
            return;
        }

        combo = 0;
        cardElement(first.id).classList.add("wrong-shake");
        cardElement(second.id).classList.add("wrong-shake");
        playTone("wrong");
        renderStats();
        window.setTimeout(() => {
            first.flipped = false;
            second.flipped = false;
            [first.id, second.id].forEach(cardId => {
                const element = cardElement(cardId);
                element.classList.remove("flipped", "wrong-shake");
                element.setAttribute("aria-pressed", "false");
            });
            openCards = [];
            lockBoard = false;
            renderStats();
        }, 900);
    }

    function resetGame(reshuffle) {
        stopTimer();
        startedAt = null;
        openCards = [];
        lockBoard = false;
        moves = 0;
        matchedPairs = 0;
        combo = 0;
        bestCombo = 0;
        focusedIndex = 0;
        memoryCards = (reshuffle ? shuffleCards(originalMemoryCards) : originalMemoryCards.slice()).map(card => ({
            ...card,
            flipped: false,
            matched: false
        }));
        renderBoard();
        renderStats();
    }

    function runConfetti() {
        const canvas = document.getElementById("confetti-canvas");
        const context = canvas.getContext("2d");
        const colors = ["#3157d5", "#047d87", "#c4553f", "#bd8a20", "#1f7a4d"];
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        const pieces = Array.from({length: 130}, () => ({
            x: Math.random() * canvas.width,
            y: -20 - Math.random() * canvas.height * 0.5,
            size: 5 + Math.random() * 8,
            speed: 2 + Math.random() * 5,
            rotation: Math.random() * Math.PI,
            color: colors[Math.floor(Math.random() * colors.length)]
        }));
        let frame = 0;
        function draw() {
            context.clearRect(0, 0, canvas.width, canvas.height);
            pieces.forEach(piece => {
                piece.y += piece.speed;
                piece.x += Math.sin((frame + piece.y) / 28);
                piece.rotation += 0.08;
                context.save();
                context.translate(piece.x, piece.y);
                context.rotate(piece.rotation);
                context.fillStyle = piece.color;
                context.fillRect(-piece.size / 2, -piece.size / 2, piece.size, piece.size * 0.55);
                context.restore();
            });
            frame += 1;
            if (frame < 170) {
                window.requestAnimationFrame(draw);
            } else {
                context.clearRect(0, 0, canvas.width, canvas.height);
            }
        }
        draw();
    }

    function showCompletion(data) {
        document.getElementById("completion-time").textContent = data.time;
        document.getElementById("completion-accuracy").textContent = `${data.accuracy}%`;
        document.getElementById("completion-moves").textContent = data.moves;
        document.getElementById("completion-combo").textContent = data.best_combo || bestCombo;
        document.getElementById("completion-xp").textContent = `+${data.xp_earned}`;
        document.getElementById("completion-level").textContent = `Level ${data.level.level}`;
        document.getElementById("completion-level-copy").textContent = `${data.level.current_xp}/${data.level.level_xp} XP`;
        document.getElementById("completion-level-bar").style.width = `${data.level.progress_percentage}%`;
        const unlocksEl = document.getElementById("completion-unlocks");
        if (data.newly_unlocked_badges.length) {
            unlocksEl.innerHTML = `<strong>Badges Unlocked</strong><span>${data.newly_unlocked_badges.join("</span><span>")}</span>`;
        } else {
            unlocksEl.innerHTML = "<strong>Badges Unlocked</strong><span>No new badges this round</span>";
        }
        modalEl.hidden = false;
        document.body.classList.add("modal-open");
        playTone("complete");
        runConfetti();
    }

    function completeGame() {
        stopTimer();
        lockBoard = true;
        fetch(completionUrl, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                difficulty: memoryDifficulty,
                elapsed_seconds: Math.max(1, elapsedSeconds()),
                moves,
                matched_pairs: matchedPairs,
                highest_combo: bestCombo
            })
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error("Could not save Memory Challenge.");
                }
                return response.json();
            })
            .then(showCompletion)
            .catch(() => {
                lockBoard = false;
            });
    }

    document.getElementById("memory-restart").addEventListener("click", () => resetGame(false));
    document.getElementById("memory-shuffle").addEventListener("click", () => resetGame(true));
    document.getElementById("memory-mute").addEventListener("click", event => {
        muted = !muted;
        event.currentTarget.setAttribute("aria-pressed", String(muted));
        event.currentTarget.textContent = muted ? "Mute" : "Sound";
    });
    document.getElementById("completion-play-again").addEventListener("click", () => {
        modalEl.hidden = true;
        document.body.classList.remove("modal-open");
        resetGame(true);
    });

    document.addEventListener("keydown", event => {
        if (!boardEl.contains(document.activeElement) && !document.activeElement.classList.contains("memory-card")) {
            return;
        }
        if (event.key === "ArrowRight" || event.key === "ArrowDown") {
            event.preventDefault();
            focusByOffset(1);
        } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
            event.preventDefault();
            focusByOffset(-1);
        } else if (event.key === "Enter") {
            event.preventDefault();
            if (document.activeElement && document.activeElement.classList.contains("memory-card")) {
                flipMemoryCard(document.activeElement.dataset.cardId);
            }
        }
    });

    window.MemoryChallenge = {
        shuffleCards,
        calculateAccuracy: currentAccuracy,
        resetGame
    };

    resetGame(false);
}());
