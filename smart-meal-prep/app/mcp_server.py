import os
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("MealPrepMCP")

# File to store the grocery list locally
GROCERY_LIST_FILE = os.path.join(os.path.dirname(__file__), "grocery_list.txt")

# Default Mock Pantry Items
DEFAULT_PANTRY = [
    "chicken breast",
    "broccoli",
    "rice",
    "olive oil",
    "garlic",
    "salt",
    "pepper",
    "onion",
    "butter",
    "soy sauce"
]

# Mock Recipe Database
RECIPES = [
    {
        "name": "Chicken & Broccoli Stir-Fry",
        "ingredients": ["chicken breast", "broccoli", "garlic", "soy sauce", "olive oil", "rice"],
        "instructions": "1. Sauté cubed chicken in olive oil. 2. Add minced garlic and broccoli florets. 3. Pour soy sauce and stir-fry. 4. Serve over warm cooked rice."
    },
    {
        "name": "Garlic Butter Chicken",
        "ingredients": ["chicken breast", "garlic", "butter", "olive oil", "salt", "pepper"],
        "instructions": "1. Season chicken with salt and pepper. 2. Heat olive oil and butter in a pan. 3. Sauté chicken with minced garlic until golden brown."
    },
    {
        "name": "Roasted Garlic Broccoli",
        "ingredients": ["broccoli", "garlic", "olive oil", "salt", "pepper"],
        "instructions": "1. Toss broccoli florets and sliced garlic in olive oil, salt, and pepper. 2. Roast in an oven at 400°F for 20 minutes."
    }
]

@mcp.tool()
def get_pantry_items() -> str:
    """Get the current list of ingredients available in the kitchen pantry.
    
    Returns:
        A comma-separated string of pantry items.
    """
    return ", ".join(DEFAULT_PANTRY)

@mcp.tool()
def search_recipes(query: str) -> str:
    """Search for available recipes matching a query string.
    
    Args:
        query: The search term (e.g., 'chicken' or 'broccoli').
        
    Returns:
        A string containing matching recipes and instructions.
    """
    matches = []
    for r in RECIPES:
        if query.lower() in r["name"].lower() or any(query.lower() in ing for ing in r["ingredients"]):
            matches.append(
                f"Recipe: {r['name']}\n"
                f"Ingredients: {', '.join(r['ingredients'])}\n"
                f"Instructions: {r['instructions']}\n"
            )
    if not matches:
        return f"No recipes found matching '{query}'."
    return "\n---\n".join(matches)

@mcp.tool()
def add_to_grocery_list(item: str, quantity: str) -> str:
    """Add a needed ingredient and its quantity to the local grocery shopping list.
    
    Args:
        item: The name of the ingredient (e.g., 'milk').
        quantity: The quantity needed (e.g., '1 gallon' or '500g').
        
    Returns:
        A confirmation message.
    """
    entry = f"{item} ({quantity})\n"
    with open(GROCERY_LIST_FILE, "a") as f:
        f.write(entry)
    return f"Successfully added {quantity} of '{item}' to the grocery list."

if __name__ == "__main__":
    # Start the stdio transport
    mcp.run()
