from pathlib import Path

from discord_webhook import DiscordWebhook, DiscordEmbed
from table2ascii import table2ascii, Alignment

from ddrcv.discord.get_webhook_url import _get_webhook_url


def create_null_player():
    return {
        "name": "null",
        "difficulty": "null",
        "max_combo": 0,
        "step_grades": [0, 0, 0, 0, 0, 0], # [marvelous, perfect, great, good, ok, miss]
        "ex_score": 0
    }


# def generate_2player_table(results):
#     lines = []
#     lines.append(f'| | {results["p1"]["name"]} | {results["p2"]["name"]} |')
#     lines.append(f'| ---: | ---: | ---: |')
#     lines.append(f'| Difficulty | {results["p1"]["difficulty"]} | {results["p1"]["difficulty"]} |')
#     lines.append(f'|  Max Combo | {results["p1"]["max_combo"]} | {results["p1"]["max_combo"]} |')
#     lines.append(f'|  Marvelous | {results["p1"]["step_grades"][0]} | {results["p1"]["step_grades"][0]} |')
#     lines.append(f'|    Perfect | {results["p1"]["step_grades"][1]} | {results["p1"]["step_grades"][1]} |')
#     lines.append(f'|      Great | {results["p1"]["step_grades"][2]} | {results["p1"]["step_grades"][2]} |')
#     lines.append(f'|       Good | {results["p1"]["step_grades"][3]} | {results["p1"]["step_grades"][3]} |')
#     lines.append(f'|       O.K. | {results["p1"]["step_grades"][4]} | {results["p1"]["step_grades"][4]} |')
#     lines.append(f'|       Miss | {results["p1"]["step_grades"][5]} | {results["p1"]["step_grades"][5]} |')
#     lines.append(f'|  **EX Score** | **{results["p1"]["step_grades"][0]}** | **{results["p1"]["step_grades"][0]}** |')
#     return '\n'.join(lines)

def generate_2player_table(results):
    output = table2ascii(
        header=["", results["p1"]["name"], results["p2"]["name"]],
        body=[
            ['Difficulty',  results["p1"]["difficulty"],          results["p2"]["difficulty"]],
            [' Max Combo',  results["p1"]['scores']["max_combo"], results["p2"]['scores']["max_combo"]],
            [' Marvelous',  results["p1"]["scores"]['marvelous'], results["p2"]["scores"]['marvelous']],
            ['   Perfect',  results["p1"]["scores"]['perfect'],   results["p2"]["scores"]['perfect']],
            ['     Great',  results["p1"]["scores"]['great'],     results["p2"]["scores"]['great']],
            ['      Good',  results["p1"]["scores"]['good'],      results["p2"]["scores"]['good']],
            ['      O.K.',  results["p1"]["scores"]['ok'],        results["p2"]["scores"]['ok']],
            ['      Miss',  results["p1"]["scores"]['miss'],      results["p2"]["scores"]['miss']],
            ['      Fast',  results["p1"]["scores"]['fast'],      results["p2"]["scores"]['fast']],
            ['      Slow',  results["p1"]["scores"]['slow'],      results["p2"]["scores"]['slow']],
        ],
        footer=['EX Score', results["p1"]['scores']['ex_score'], results["p2"]['scores']['ex_score']],
        alignments=[Alignment.RIGHT] * 3
    )
    output = ['```', output, '```']
    output = '\n'.join(output)
    return output


def generate_1player_table(results):
    output = table2ascii(
        header=["", results["name"]],
        body=[
            ['Difficulty',  results["difficulty"]],
            [' Max Combo',  results['scores']["max_combo"]],
            [' Marvelous',  results["scores"]['marvelous']],
            ['   Perfect',  results["scores"]['perfect']],
            ['     Great',  results["scores"]['great']],
            ['      Good',  results["scores"]['good']],
            ['      O.K.',  results["scores"]['ok']],
            ['      Miss',  results["scores"]['miss']],
            ['      Fast',  results["scores"]['fast']],
            ['      Slow',  results["scores"]['slow']],
        ],
        footer=['EX Score', results['scores']['ex_score']],
        alignments=[Alignment.RIGHT] * 2
    )
    output = ['```', output, '```']
    output = '\n'.join(output)
    return output


def get_2player_embed(results):
    """
    {
        "song": "Macho Gang",
        "stage": "1"
        "p1":
        {
            "name": "ZVIDUN",
            "difficulty": "Expert",
            "max_combo": 123,
            "step_grades": [69, 42, 17, 9, 3, 0], # [marvelous, perfect, great, good, ok, miss]
            "ex_score": 3142
        },
        "p2":
        {
            "name": "DUSK",
            "difficulty": "Beginner",
            "max_combo": 9,
            "step_grades": [1, 2, 3, 4, 5, 6], # [marvelous, perfect, great, good, ok, miss]
            "ex_score": 13
        }
    }
    """
    p1 = results['p1']
    p2 = results['p2']
    embed_title = f'{p1["name"]} vs {p2["name"]} - {results.get("stage", "*UNKNOWN*")}'
    embed = DiscordEmbed(title=embed_title)
    embed.add_embed_field(name='Song', value=results.get('song', "*UNKNOWN*"), inline=False)

    print(generate_2player_table(results))

    embed.add_embed_field(name='Steps', value=generate_2player_table(results), inline=False)

    p1_ex = p1['scores']['ex_score']
    p2_ex = p2['scores']['ex_score']
    if p1_ex == p2_ex:
        winner_str = '*DRAW*'
    else:
        winner_str = f'{p1["name"] if p1_ex > p2_ex else p2["name"]} (+{abs(p1_ex - p2_ex)})'

    embed.add_embed_field(name='Winner', value=winner_str, inline=False)
    return embed


def get_1player_embed(results):
    player = results.get('p1', None)
    if player is None:
        player = results.get('p2', None)
    embed_title = f'{player["name"]} - {results.get("stage", "*UNKNOWN*")}'
    embed = DiscordEmbed(title=embed_title)
    embed.add_embed_field(name='Song', value=results.get('song', "*UNKNOWN*"), inline=False)

    print(generate_1player_table(player))

    embed.add_embed_field(name='Steps', value=generate_1player_table(player), inline=False)

    return embed


def get_song_results_embed(results):
    """
    {
        "song": "Macho Gang",
        "stage": "1"
        "p1":
        {
            "name": "ZVIDUN",
            "difficulty": "Expert",
            "max_combo": 123,
            "step_grades": [69, 42, 17, 9, 3, 0], # [marvelous, perfect, great, good, ok, miss]
            "ex_score": 3142
        },
        "p2":
        {
            "name": "DUSK",
            "difficulty": "Beginner",
            "max_combo": 9,
            "step_grades": [1, 2, 3, 4, 5, 6], # [marvelous, perfect, great, good, ok, miss]
            "ex_score": 13
        }
    }
    """

    if 'p1' in results and 'p2' in results:
        return get_2player_embed(results)
    elif 'p1' in results or 'p2' in results:
        return get_1player_embed(results)
    return None


def push_song_results(results, screenshot_path=None):
    webhook = DiscordWebhook(url=_get_webhook_url())

    embed = get_song_results_embed(results)
    embed.set_footer(text="Generated")
    embed.set_timestamp()

    if screenshot_path is not None:
        screenshot_path = Path(screenshot_path)
        if not screenshot_path.is_file():
            embed.add_embed_field(name='Runtime Error', value=f'File {str(screenshot_path)} does not exist')
        else:
            with open(screenshot_path, "rb") as f:
                webhook.add_file(file=f.read(), filename=screenshot_path.name)
                # embed.set_thumbnail(url=f"attachment://{screenshot_path.name}")
                embed.set_image(url=f"attachment://{screenshot_path.name}")

    webhook.add_embed(embed)

    response = webhook.execute()
    print('response: ', response)


if __name__ == "__main__":
    # results = {
    #     "song": "So Deep",
    #     "p1": create_null_player(),
    #     "p2": create_null_player()
    # }

    results = {
        "song": "Macho Gang",
        "stage": "1",
        "p1":
        {
            "name": "ZVIDUN",
            "difficulty": "Expert",
            "max_combo": 123,
            "step_grades": [69, 42, 17, 9, 3, 0],  # [marvelous, perfect, great, good, ok, miss]
            "ex_score": 3142
        },
        "p2":
        {
            "name": "DUSK",
            "difficulty": "Beginner",
            "max_combo": 9,
            "step_grades": [1, 2, 3, 4, 5, 6],  # [marvelous, perfect, great, good, ok, miss]
            "ex_score": 13
        }
    }

    push_song_results(results, screenshot_path='../../state_images/stage_rank.png')




