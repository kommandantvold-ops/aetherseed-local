# Reading texts

Material for the reading soak of 25 September 2026 (build log step 38), chosen
by Andreas: the **Song of Songs** read to the node verse by verse, as the source
its rings grow from, and **Genesis** entered as facts from its owner.

He asked for the New Living Translation. That text is under copyright and is
not reproduced here; he chose the World English Bible instead.

| file | what |
|---|---|
| `genesis.web.jsonl` | Genesis, 1533 verses, one JSON object per line |
| `song-of-songs.web.jsonl` | Song of Songs, 117 verses, same form |
| `genesis-probes.json` | the questions the soak asks, each with the verses that answer it and the words an answer should contain |
| `from_vpl.py` | makes the two `.jsonl` files from the source file |

## Source

**The World English Bible**, from eBible.org, in its verse-per-line download
`eng-web_vpl.zip` (files inside dated 2026-09-22). Its `eng-web_about.htm`:

> The World English Bible is in the Public Domain. That means that it is not
> copyrighted. However, "World English Bible" is a Trademark of eBible.org.
> [...] All we ask is that if you CHANGE the actual text of the World English
> Bible in any way, you not call the result the World English Bible any more.

The text here is not changed: `from_vpl.py` copies each verse of `GEN` and `SOL`
from `eng-web_vpl.txt` as it stands, adding only the reference. Nothing is
normalised - the curly quotes are the source's.

```
89823c271c3fcbe1f21818beed3fec0c34d5bffaa9b0e977114ed4e8f5036efa  eng-web_vpl.zip
75b5b2f8f290ded9b2fa51a9b3ff2f9e1871708f9761bd68e34b5aaba006e667  eng-web_vpl.txt
896b07e475a9f35839c6e6cf4865a5735bff68a3e3c666293544bcde7c5a9271  genesis.web.jsonl
34e2cd126341d04685da1762392cbc3200ba959acbe4f6bc891150ffed01b500  song-of-songs.web.jsonl
```

To check: unzip, run `python3 tools/texts/from_vpl.py eng-web_vpl.txt <dir>`,
and compare the two `.jsonl` hashes. The zip itself is not in the repository.
