import re

from models import Chapter, Textbook


def normalize_catalog_value(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


CBSE_ENGLISH_TEXTBOOKS = [
    {
        "class_level": 6,
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
]


def seed_cbse_textbook_catalog(session):
    for book_data in CBSE_ENGLISH_TEXTBOOKS:
        normalized_name = normalize_catalog_value(book_data["name"])
        textbook = Textbook.query.filter_by(
            board="CBSE",
            subject="English",
            class_level=book_data["class_level"],
            normalized_name=normalized_name,
        ).first()
        if textbook is None:
            textbook = Textbook(
                board="CBSE",
                subject="English",
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
        for chapter_number, title in enumerate(book_data["chapters"], start=1):
            normalized_title = normalize_catalog_value(title)
            chapter = existing_chapters.get(normalized_title)
            if chapter is None:
                session.add(
                    Chapter(
                        textbook_id=textbook.id,
                        chapter_number=chapter_number,
                        title=title,
                        normalized_title=normalized_title,
                    )
                )
            else:
                chapter.chapter_number = chapter_number
                chapter.title = title
                chapter.normalized_title = normalized_title
    session.commit()
