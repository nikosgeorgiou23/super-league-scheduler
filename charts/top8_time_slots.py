"""Recreate the chart from the eight results recorded in the conversation.

The original raw datasets and analysis scripts were deleted at user request.
These are the previously computed pooled means, not a new data retrieval.
Selection: Monday/Saturday/Sunday, two-hour bins, count >= 15, rounds 1-25,
seasons 2023-24/2024-25/2025-26, only matches with result and known kickoff.
"""
from pathlib import Path
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent
with (HERE/'top8_time_slots.csv').open(encoding='utf-8-sig',newline='') as stream:
    HISTORY=list(csv.DictReader(stream))
ROWS=[(row['day'],row['window'],float(row['mean_strength']),int(row['match_count']))
      for row in sorted(HISTORY,key=lambda row:-float(row['mean_strength']))]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,
                     'axes.spines.top':False,'axes.spines.right':False})
fig,ax=plt.subplots(figsize=(14,7.5),facecolor='#f7f9fc')
fig.subplots_adjust(left=.08,right=.98,bottom=.19,top=.76)
ax.set_facecolor('white')
bars=ax.bar(range(8),[r[2] for r in ROWS],width=.66,color='#e87924',zorder=3)
for i,(_,_,mean,n) in enumerate(ROWS):
    ax.text(i,mean+2,f'{mean:.2f}\nn={n}',ha='center',va='bottom',weight='bold',fontsize=11,color='#914313')
ax.set(xticks=range(8),xticklabels=[f'{day}\n{window}' for day,window,_,_ in ROWS],
       ylabel='Μέση δυναμικότητα: Σ(Fᵢ + Fⱼ) / πλήθος αγώνων',ylim=(0,150))
ax.grid(axis='y',color='#dce3ec',zorder=0)
fig.text(.08,.93,'Τα 8 επικρατέστερα δίωρα time slots',fontsize=22,weight='bold',color='#16263c')
fig.text(.08,.86,'Μόνο Σάββατο, Κυριακή και Δευτέρα · τουλάχιστον 15 αγώνες ανά slot',fontsize=12,color='#41516a')
fig.text(.08,.81,'Κατάταξη από τον μέσο Fᵢ+Fⱼ · πρώτες 25 αγωνιστικές regular season · 2023–24, 2024–25, 2025–26',fontsize=10,color='#41516a')
fig.text(.08,.07,'n = πλήθος αγώνων. Η σεζόν 2025–26 είναι ελλιπής στην πηγή· χρησιμοποιήθηκαν μόνο εγγραφές με ώρα και αποτέλεσμα.',fontsize=9,color='#596579')
fig.text(.08,.035,'Αναδημιουργία από τις προηγουμένως υπολογισμένες τιμές της ανάλυσης της 2026-10-30, χωρίς νέα λήψη δεδομένων.',fontsize=9,color='#596579')
fig.savefig(HERE/'top8_time_slots.png',dpi=180,facecolor=fig.get_facecolor())
plt.close(fig)
print(HERE/'top8_time_slots.png')

if __name__=='__main__':
    assert len(ROWS)==8 and all(row[3]>=15 for row in ROWS)
    assert all(ROWS[i][2]>=ROWS[i+1][2] for i in range(7))
