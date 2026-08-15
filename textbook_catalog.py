import re

from models import Chapter, Textbook


def normalize_catalog_value(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def normalize_catalog_subject(value):
    normalized = normalize_catalog_value(value)
    if normalized in {"math", "maths"}:
        return "mathematics"
    if normalized in {"sst", "social studies"}:
        return "social science"
    return normalized


def subject_matches_catalog_subject(stored_subject, selected_subject):
    if not selected_subject:
        return True
    return normalize_catalog_subject(stored_subject) == normalize_catalog_subject(selected_subject)


def chapter_title(chapter_data):
    if isinstance(chapter_data, dict):
        return chapter_data["title"]
    return chapter_data


def chapter_search_keywords(chapter_data):
    if not isinstance(chapter_data, dict):
        return ""
    keywords = chapter_data.get("keywords", [])
    return " ".join(
        dict.fromkeys(
            normalized_keyword
            for keyword in keywords
            for normalized_keyword in [normalize_catalog_value(keyword)]
            if normalized_keyword
        )
    )


CBSE_TEXTBOOKS = [
    {
        "class_level": 6,
        "subject": "English",
        "name": "Poorvi",
        "chapters": [
            "A Bottle of Dew",
            "The Raven and the Fox",
            "Rama to the Rescue",
            "The Unlikely Best Friends",
            "A Friend's Prayer",
            "The Chair",
            "Neem Baba",
            "What a Bird Thought",
            "Spices that Heal Us",
            "Change of Heart",
            "The Winner",
            "Yoga - A Way of Life",
            "Hamara Bharat - Incredible India!",
            "The Kites",
            "Ila Sachani: Embroidering Dreams with her Feet",
            "National War Memorial",
        ],
    },
    {
        "class_level": 7,
        "subject": "English",
        "name": "Poorvi",
        "chapters": [
            "The Day the River Spoke",
            "Try Again",
            "Three Days to See",
            "Animals, Birds, and Dr. Dolittle",
            "A Funny Man",
            "Say the Right Thing",
            "My Brother's Great Invention",
            "Paper Boats",
            "North, South, East, West",
            "The Tunnel",
            "Travel",
            "Conquering the Summit",
            "A Homage to Our Brave Soldiers",
            "My Dear Soldiers",
            "Rani Abbakka",
        ],
    },
    {
        "class_level": 8,
        "subject": "English",
        "name": "Poorvi",
        "chapters": [
            "The Wit that Won Hearts",
            "A Concrete Example",
            "Wisdom Paves the Way",
            "A Tale of Valour: Major Somnath Sharma and the Battle of Badgam",
            "Somebody's Mother",
            "Verghese Kurien - I Too Had A Dream",
            "The Case of the Fifth Word",
            "The Magic Brush of Dreams",
            "Spectacular Wonders",
            "The Cherry Tree",
            "Harvest Hymn",
            "Waiting for the Rain",
            "Feathered Friend",
            "Magnifying Glass",
            "Bibha Chowdhuri: The Beam of Light that Lit the Path for Women in Indian Science",
        ],
    },
    {
        "class_level": 9,
        "subject": "English",
        "name": "Kaveri",
        "chapters": [
            "How I Taught My Grandmother to Read",
            "Bharat Our Land",
            "The Pot Maker",
            "Gifts of Grace: Honouring Our Vocations",
            "Winds of Change",
            "Canvas of Soil",
            "Vitamin-M",
            "I Cannot Remember My Mother",
            "The World of Limitless Possibilities",
            "Nine Gold Medals",
            "Twin Melodies",
            "A Friend Found in Music",
            "Carrier of Words",
            "Words",
            "Follow That Dream",
            "Believe in Yourself",
        ],
    },
    {
        "class_level": 10,
        "subject": "English",
        "name": "First Flight",
        "chapters": [
            "A Letter to God",
            "Dust of Snow",
            "Fire and Ice",
            "Nelson Mandela: Long Walk to Freedom",
            "A Tiger in the Zoo",
            "Two Stories about Flying",
            "His First Flight",
            "Black Aeroplane",
            "How to Tell Wild Animals",
            "The Ball Poem",
            "From the Diary of Anne Frank",
            "Amanda!",
            "Glimpses of India",
            "A Baker from Goa",
            "Coorg",
            "Tea from Assam",
            "The Trees",
            "Mijbil the Otter",
            "Fog",
            "Madam Rides the Bus",
            "The Tale of Custard the Dragon",
            "The Sermon at Benares",
            "For Anne Gregory",
            "The Proposal",
        ],
    },
    {
        "class_level": 10,
        "subject": "English",
        "name": "Footprints Without Feet",
        "chapters": [
            "A Triumph of Surgery",
            "The Thief's Story",
            "The Midnight Visitor",
            "A Question of Trust",
            "Footprints Without Feet",
            "The Making of a Scientist",
            "The Necklace",
            "Bholi",
            "The Book That Saved the Earth",
        ],
    },
    {
        "class_level": 6,
        "subject": "Mathematics",
        "name": "Ganita Prakash",
        "chapters": [
            "Patterns in Mathematics",
            "Lines and Angles",
            "Number Play",
            "Data Handling and Presentation",
            "Prime Time",
            "Perimeter and Area",
            "Fractions",
            "Playing with Constructions",
            "Symmetry",
            "The Other Side of Zero",
        ],
    },
    {
        "class_level": 7,
        "subject": "Mathematics",
        "name": "Ganita Prakash",
        "chapters": [
            "Large Numbers Around Us",
            "Arithmetic Expressions",
            "A Peek Beyond the Point",
            "Expressions using Letter-Numbers",
            "Parallel and Intersecting Lines",
            "Number Play",
            "A Tale of Three Intersecting Lines",
            "Working with Fractions",
        ],
    },
    {
        "class_level": 8,
        "subject": "Mathematics",
        "name": "Ganita Prakash Part-I",
        "chapters": [
            "A Square and A Cube",
            "Power Play",
            "A Story of Numbers",
            "Quadrilaterals",
            "Number Play",
            "We Distribute, Yet Things Multiply",
            "Proportional Reasoning-1",
        ],
    },
    {
        "class_level": 8,
        "subject": "Mathematics",
        "name": "Ganita Prakash Part-II",
        "chapters": [
            "Fractions in Disguise",
            "The Baudhayana-Pythagoras Theorem",
            "Proportional Reasoning-2",
            "Exploring Some Geometric Themes",
            "Tales by Dots and Lines",
            "Algebra Play",
            "Area",
        ],
    },
    {
        "class_level": 9,
        "subject": "Mathematics",
        "name": "Ganita Manjari",
        "chapters": [
            "Orienting Yourself: The Use of Coordinates",
            "Introduction to Linear Polynomials",
            "The World of Numbers",
            "Exploring Algebraic Identities",
            "I’m Up and Down, and Round and Round",
            "Measuring Space: Perimeter and Area",
            "The Mathematics of Maybe: Introduction to Probability",
            "Predicting What Comes Next: Exploring Sequences and Progressions",
        ],
    },
    {
        "class_level": 9,
        "subject": "Mathematics",
        "name": "Mathematics",
        "chapters": [
            "Number Systems",
            "Polynomials",
            "Coordinate Geometry",
            "Linear Equations in Two Variables",
            "Introduction to Euclid's Geometry",
            "Lines and Angles",
            "Triangles",
            "Quadrilaterals",
            "Circles",
            "Heron's Formula",
            "Surface Areas and Volumes",
            "Statistics",
        ],
    },
    {
        "class_level": 10,
        "subject": "Mathematics",
        "name": "Mathematics",
        "chapters": [
            "Real Numbers",
            "Polynomials",
            "Pair of Linear Equations in Two Variables",
            "Quadratic Equations",
            "Arithmetic Progressions",
            "Triangles",
            "Coordinate Geometry",
            "Introduction to Trigonometry",
            "Some Applications of Trigonometry",
            "Circles",
            "Areas Related to Circles",
            "Surface Areas and Volumes",
            "Statistics",
            "Probability",
        ],
    },
    {
        "class_level": 6,
        "subject": "Science",
        "name": "Curiosity",
        "chapters": [
            "The Wonderful World of Science",
            "Diversity in the Living World",
            "Mindful Eating: A Path to a Healthy Body",
            "Exploring Magnets",
            "Measurement of Length and Motion",
            "Materials Around Us",
            "Temperature and its Measurement",
            "A Journey through States of Water",
            "Methods of Separation in Everyday Life",
            "Living Creatures: Exploring their Characteristics",
            "Nature's Treasures",
            "Beyond Earth",
        ],
    },
    {
        "class_level": 7,
        "subject": "Science",
        "name": "Curiosity",
        "chapters": [
            "The Ever-Evolving World of Science",
            "Exploring Substances: Acidic, Basic, and Neutral",
            "Electricity: Circuits and their Components",
            "The World of Metals and Non-metals",
            "Changes Around Us: Physical and Chemical",
            "Adolescence: A Stage of Growth and Change",
            "Heat Transfer in Nature",
            "Measurement of Time and Motion",
            "Life Processes in Animals",
            "Life Processes in Plants",
            "Light: Shadows and Reflections",
            "Earth, Moon, and the Sun",
        ],
    },
    {
        "class_level": 8,
        "subject": "Science",
        "name": "Science",
        "chapters": [
            "Crop Production and Management",
            "Microorganisms: Friend and Foe",
            "Synthetic Fibres and Plastics",
            "Materials: Metals and Non-Metals",
            "Coal and Petroleum",
            "Combustion and Flame",
            "Conservation of Plants and Animals",
            "Cell — Structure and Functions",
            "Reproduction in Animals",
            "Reaching the Age of Adolescence",
            "Force and Pressure",
            "Friction",
            "Sound",
            "Chemical Effects of Electric Current",
            "Some Natural Phenomena",
            "Light",
            "Stars and the Solar System",
            "Pollution of Air and Water",
        ],
    },
    {
        "class_level": 9,
        "subject": "Science",
        "name": "Exploration",
        "chapters": [
            "Exploration: Entering the World of Secondary Science",
            "Cell: The Building Block of Life",
            "Tissues in Action",
            "Describing Motion Around Us",
            "Exploring Mixtures and their Separation",
            "How Forces Affect Motion",
            "Work, Energy, and Simple Machines",
            "Journey Inside the Atom",
            "Atomic Foundations of Matter",
            "Sound Waves: Characteristics and Applications",
            "Reproduction: How Life Continues",
            "Patterns in Life: Diversity and Classification",
            "Earth as a System: Energy, Matter, and Life",
        ],
    },
    {
        "class_level": 9,
        "subject": "Science",
        "name": "Science",
        "chapters": [
            "Matter in Our Surroundings",
            "Is Matter Around Us Pure",
            "Atoms and Molecules",
            "Structure of the Atom",
            "The Fundamental Unit of Life",
            "Tissues",
            "Motion",
            "Force and Laws of Motion",
            "Gravitation",
            "Work and Energy",
            "Sound",
            "Improvement in Food Resources",
        ],
    },
    {
        "class_level": 10,
        "subject": "Science",
        "name": "Science",
        "chapters": [
            "Chemical Reactions and Equations",
            "Acids, Bases and Salts",
            "Metals and Non-metals",
            "Carbon and its Compounds",
            "Life Processes",
            "Control and Coordination",
            "How do Organisms Reproduce?",
            "Heredity",
            "Light - Reflection and Refraction",
            "The Human Eye and the Colourful World",
            "Electricity",
            "Magnetic Effects of Electric Current",
            "Our Environment",
        ],
    },
    {
        "class_level": 6,
        "subject": "Social Science",
        "name": "Exploring Society: India and Beyond",
        "chapters": [
            "Locating Places on the Earth",
            "Oceans and Continents",
            "Landforms and Life",
            "Timeline and Sources of History",
            "India, That Is Bharat",
            "The Beginnings of Indian Civilisation",
            "India's Cultural Roots",
            "Unity in Diversity, or 'Many in the One'",
            "Family and Community",
            "Grassroots Democracy - Part 1: Governance",
            "Grassroots Democracy - Part 2: Local Government in Rural Areas",
            "Grassroots Democracy - Part 3: Local Government in Urban Areas",
            "The Value of Work",
            "Economic Activities Around Us",
        ],
    },
    {
        "class_level": 7,
        "subject": "Social Science",
        "name": "Exploring Society: India and Beyond",
        "chapters": [
            "Geographical Diversity of India",
            "Understanding the Weather",
            "Climates of India",
            "New Beginnings: Cities and States",
            "The Rise of Empires",
            "The Age of Reorganisation",
            "The Gupta Era: An Age of Tireless Creativity",
            "How the Land Becomes Sacred",
            "From the Rulers to the Ruled: Types of Governments",
            "The Constitution of India - An Introduction",
            "From Barter to Money",
            "Understanding Markets",
        ],
    },
    {
        "class_level": 8,
        "subject": "Social Science",
        "name": "Exploring Society: India and Beyond Part-I",
        "chapters": [
            "Natural Resources and Their Use",
            "Reshaping India's Political Map",
            "The Rise of the Marathas",
            "The Colonial Era in India",
            "Universal Franchise and India's Electoral System",
            "The Parliamentary System: Legislature and Executive",
            "Factors of Production",
        ],
    },
    {
        "class_level": 9,
        "subject": "Social Science",
        "name": "Understanding Society: India and Beyond",
        "chapters": [
            {
                "title": "Understanding Social Science",
                "keywords": [
                    "social science",
                    "society",
                    "history",
                    "geography",
                    "political science",
                    "economics",
                    "culture",
                    "India",
                    "community",
                    "social studies",
                    "sst",
                ],
            },
            {
                "title": "Shaping of the Earth's Surface",
                "keywords": [
                    "earth surface",
                    "landforms",
                    "mountains",
                    "plains",
                    "plateaus",
                    "rivers",
                    "erosion",
                    "weathering",
                    "deposition",
                    "tectonic plates",
                    "earthquake",
                    "volcano",
                    "soil",
                    "rocks",
                    "relief features",
                ],
            },
            {
                "title": "Atmosphere and Climate",
                "keywords": [
                    "climate",
                    "weather",
                    "monsoon",
                    "rainfall",
                    "temperature",
                    "winds",
                    "humidity",
                    "air pressure",
                    "atmosphere",
                    "seasons",
                    "clouds",
                    "precipitation",
                    "cyclone",
                    "greenhouse effect",
                    "climatic regions",
                ],
            },
            {
                "title": "Early Humans and Beginning of Civilisation",
                "keywords": [
                    "early humans",
                    "human evolution",
                    "hunter gatherers",
                    "stone age",
                    "palaeolithic",
                    "neolithic",
                    "tools",
                    "fire",
                    "farming",
                    "domestication",
                    "settlements",
                    "civilisation",
                    "river valleys",
                    "archaeology",
                ],
            },
            {
                "title": "State and Society up to 1000 CE",
                "keywords": [
                    "state",
                    "society",
                    "kingdoms",
                    "empires",
                    "janapadas",
                    "mauryas",
                    "guptas",
                    "administration",
                    "trade",
                    "towns",
                    "religion",
                    "culture",
                    "medieval",
                    "ancient India",
                    "1000 CE",
                    "early historical period",
                ],
            },
            {
                "title": "Democracy",
                "keywords": [
                    "democracy",
                    "government",
                    "citizens",
                    "constitution",
                    "rights",
                    "participation",
                    "equality",
                    "freedom",
                    "representatives",
                    "people's rule",
                    "accountability",
                    "rule of law",
                    "civic life",
                ],
            },
            {
                "title": "Elections",
                "keywords": [
                    "election",
                    "voting",
                    "candidate",
                    "political parties",
                    "Election Commission",
                    "ballot",
                    "vote",
                    "electoral roll",
                    "constituency",
                    "campaign",
                    "polling",
                    "voter",
                    "universal adult franchise",
                    "free and fair elections",
                ],
            },
            {
                "title": "Building Blocks in Economics: The Problem of Choice",
                "keywords": [
                    "economics",
                    "choice",
                    "scarcity",
                    "resources",
                    "needs",
                    "wants",
                    "opportunity cost",
                    "production",
                    "consumption",
                    "goods",
                    "services",
                    "allocation",
                    "decision making",
                    "economic problem",
                ],
            },
            {
                "title": "The Price Puzzle: What Drives the Market",
                "keywords": [
                    "price",
                    "market",
                    "demand",
                    "supply",
                    "buyers",
                    "sellers",
                    "competition",
                    "cost",
                    "profit",
                    "market price",
                    "equilibrium",
                    "consumer",
                    "producer",
                    "trade",
                    "inflation",
                ],
            },
        ],
    },
    {
        "class_level": 10,
        "subject": "Social Science",
        "name": "India and the Contemporary World-II",
        "chapters": [
            "The Rise of Nationalism in Europe",
            "Nationalism in India",
            "The Making of a Global World",
            "The Age of Industrialisation",
            "Print Culture and the Modern World",
        ],
    },
    {
        "class_level": 10,
        "subject": "Social Science",
        "name": "Contemporary India-II",
        "chapters": [
            "Resources and Development",
            "Forest and Wildlife Resources",
            "Water Resources",
            "Agriculture",
            "Minerals and Energy Resources",
            "Manufacturing Industries",
            "Lifelines of National Economy",
        ],
    },
    {
        "class_level": 10,
        "subject": "Social Science",
        "name": "Democratic Politics-II",
        "chapters": [
            "Power-sharing",
            "Federalism",
            "Gender, Religion and Caste",
            "Political Parties",
            "Outcomes of Democracy",
        ],
    },
    {
        "class_level": 10,
        "subject": "Social Science",
        "name": "Understanding Economic Development",
        "chapters": [
            "Development",
            "Sectors of the Indian Economy",
            "Money and Credit",
            "Globalisation and the Indian Economy",
            "Consumer Rights",
        ],
    },
]


CBSE_ENGLISH_TEXTBOOKS = [
    textbook for textbook in CBSE_TEXTBOOKS if textbook["subject"] == "English"
]


def seed_cbse_textbook_catalog(session):
    for book_data in CBSE_TEXTBOOKS:
        normalized_name = normalize_catalog_value(book_data["name"])
        textbook = Textbook.query.filter_by(
            board="CBSE",
            subject=book_data["subject"],
            class_level=book_data["class_level"],
            normalized_name=normalized_name,
        ).first()
        if textbook is None:
            textbook = Textbook(
                board="CBSE",
                subject=book_data["subject"],
                class_level=book_data["class_level"],
                name=book_data["name"],
                normalized_name=normalized_name,
                is_active=True,
            )
            session.add(textbook)
            session.flush()
        else:
            textbook.name = book_data["name"]
            textbook.normalized_name = normalized_name
            textbook.is_active = True

        existing_chapters = {
            chapter.normalized_title: chapter
            for chapter in Chapter.query.filter_by(textbook_id=textbook.id).all()
        }
        for chapter_number, chapter_data in enumerate(book_data["chapters"], start=1):
            title = chapter_title(chapter_data)
            normalized_title = normalize_catalog_value(title)
            search_keywords = chapter_search_keywords(chapter_data)
            chapter = existing_chapters.get(normalized_title)
            if chapter is None:
                session.add(
                    Chapter(
                        textbook_id=textbook.id,
                        chapter_number=chapter_number,
                        title=title,
                        normalized_title=normalized_title,
                        search_keywords=search_keywords,
                    )
                )
            else:
                chapter.chapter_number = chapter_number
                chapter.title = title
                chapter.normalized_title = normalized_title
                chapter.search_keywords = search_keywords

    latest_class_9_sst = Textbook.query.filter_by(
        board="CBSE",
        subject="Social Science",
        class_level=9,
        normalized_name=normalize_catalog_value("Understanding Society: India and Beyond"),
    ).order_by(Textbook.id.asc()).first()
    if latest_class_9_sst is not None:
        Textbook.query.filter(
            Textbook.board == "CBSE",
            Textbook.subject == "Social Science",
            Textbook.class_level == 9,
            Textbook.id != latest_class_9_sst.id,
        ).update({"is_active": False}, synchronize_session=False)
    session.commit()
