import google.generativeai as genai

from config import GEMINI_API_KEY


def main():
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(
        "Explain photosynthesis in simple words for a class 9 student."
    )
    print(response.text)


if __name__ == "__main__":
    main()
