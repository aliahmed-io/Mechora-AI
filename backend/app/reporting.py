"""Multi-page course-demo reports built from saved results and model metadata."""
import io
import json
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from backend.app.model_store import saved_metadata

def analysis_pdf(run,session,dataset_name):
    rows=json.loads(run.predictions_json);meta=saved_metadata(session,run.model_version)
    output=io.BytesIO()
    doc=SimpleDocTemplate(output,pagesize=(595,842),leftMargin=40,rightMargin=40,topMargin=115,bottomMargin=55,title='Mechora AI analysis report',author='Mechora AI')
    style=ParagraphStyle('body',fontName='Helvetica',fontSize=9,leading=14,textColor=colors.HexColor('#171514'),spaceAfter=9,splitLongWords=True)
    heading=ParagraphStyle('heading',parent=style,fontName='Helvetica-Bold',fontSize=12,leading=18,spaceBefore=12,spaceAfter=12)
    def p(text,kind=style):return Paragraph(escape(str(text)),kind)
    def frame(canvas,document):
        canvas.saveState();canvas.setFillColor(colors.HexColor('#590907'));canvas.rect(0,760,595,82,fill=1,stroke=0)
        canvas.setFillColor(colors.HexColor('#F5F0E8'));canvas.setFont('Times-Roman',28);canvas.drawString(40,792,'MECHORA AI')
        canvas.setFont('Helvetica',10);canvas.drawString(40,772,'Maintenance intelligence / analysis report')
        canvas.setFillColor(colors.HexColor('#827b70'));canvas.setFont('Helvetica',8)
        canvas.drawString(40,30,'Research edition / saved analysis and model provenance')
        canvas.drawRightString(555,30,f'Page {document.page}');canvas.restoreState()
    average=sum(r['probability'] for r in rows)/len(rows)
    data_note='Training data was supplied by a user; its source and label quality require independent verification.' if meta.get('data_origin') else 'The default model uses the synthetic UCI AI4I 2020 dataset.'
    story=[p(f'Dataset: {dataset_name}'),p(f'Analysis: {run.id}'),p(f'Created: {run.created_at}'),p(f'Model: {run.model_version} / {meta.get("selected_model","Historical model")}'),p(f'Observations: {len(rows):,} | High risk: {sum(r["risk"]=="High" for r in rows):,} | Mean failure estimate: {average:.2%}'),p(f'Risk boundaries: watch >= {float(run.watch):.2%}; high >= {float(run.high):.2%}')]
    test=meta.get('test_metrics')
    if test:
        story.extend([p('Model evaluation (original held-out test set)',heading),p(f'Precision {test["precision"]:.2%} | Recall {test["recall"]:.2%} | F1 {test["f1"]:.4f} | ROC-AUC {test["roc_auc"]:.4f} | Average precision {test["pr_auc"]:.4f}'),p('Evaluation metrics describe the held-out portion of the model training dataset, not verified outcomes of these uploaded observations.')])
    context_rows=[r for r in rows if r.get('machine_id') and r.get('observed_at')]
    if context_rows:story.append(p(f'Machine context: {len({r["machine_id"] for r in context_rows})} machines. Observation range: {min(r["observed_at"] for r in context_rows)} to {max(r["observed_at"] for r in context_rows)}. IDs and timestamps are excluded from model inputs.'))
    story.extend([p('Interpretation and limitations',heading),p('Probabilities are classification estimates, not safety guarantees or time-to-failure predictions. '+data_note+' Real-world generalization has not been established. Local median replacement sensitivities are nonadditive and are not causal effects.'),p('Highest-risk observations',heading),p('Up to 100 observations, sorted by estimated failure probability. The CSV export includes every record in the selected analysis.')])
    table_rows=[['Observation','Type','Air K','Process K','Speed rpm','Torque Nm','Wear min','Estimate','Risk']]
    for r in sorted(rows,key=lambda r:r['probability'],reverse=True)[:100]:
        table_rows.append([r['record_id'],r['Type'],f'{r["Air temperature [K]"]:.1f}',f'{r["Process temperature [K]"]:.1f}',f'{r["Rotational speed [rpm]"]:g}',f'{r["Torque [Nm]"]:.1f}',f'{r["Tool wear [min]"]:g}',f'{r["probability"]:.2%}',r['risk']])
    table=Table(table_rows,colWidths=[80,25,45,50,55,50,40,65,45],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTNAME',(0,1),(-1,-1),'Helvetica'),('FONTSIZE',(0,0),(-1,-1),7),('LEADING',(0,0),(-1,-1),11),('TEXTCOLOR',(0,0),(-1,0),colors.HexColor('#590907')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E8D2B5')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#F5F0E8'),colors.white]),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#B99A72'))]))
    source_note=f'Training source: {meta.get("dataset","User-supplied data")}. Source and outcome labels were supplied by the user and require independent verification.' if meta.get('data_origin') else 'Dataset: Matzka, S. (2020). AI4I 2020 Predictive Maintenance Dataset. UCI Machine Learning Repository. DOI: 10.24432/C5HS5C. CC BY 4.0.'
    story.extend([Spacer(1,8),table,Spacer(1,15),p(source_note)])
    doc.build(story,onFirstPage=frame,onLaterPages=frame)
    return output.getvalue()
