from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import uuid

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime
from frappe.utils.file_manager import save_file

from hospitality_suite import api,privacy


class TestPrivacy(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(frappe.db.rollback)
        frappe.set_user("Administrator")
        self.prop=frappe.get_doc("HS Property",{"property_name":"Hotel Jardín Demo"})
        self.old=now_datetime()-timedelta(days=400)
        self.queue_patch=patch("hospitality_suite.privacy.queue")
        self.queue=self.queue_patch.start()
        self.addCleanup(self.queue_patch.stop)

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def age(self,doc,**extra):
        frappe.db.set_value(doc.doctype,doc.name,dict(modified=self.old,**extra),update_modified=False)
        doc.reload()

    def guest(self,with_file=True):
        token=uuid.uuid4().hex
        result=api.create_guest(self.prop.name,dict(full_name="Huésped de retención sintético "+token[:7],identity_type="Ficticia",identity_number="FICTICIO-"+token),token)
        doc=frappe.get_doc("HS Guest",result["guest"])
        doc.identity_number+="-revisado"
        doc.save()
        file=None
        if with_file:
            file=save_file("identificacion-sintetica-"+token+".txt",("Identificacion ficticia "+token).encode(),doc.doctype,doc.name,is_private=1)
            doc.identity_file=file.file_url
            doc.save()
            # Saving an Attach field can create a second native File reference.
            for attached in privacy.files_for(doc):
                self.age(frappe.get_doc("File",attached.name),creation=self.old)
            file.reload()
        self.age(doc)
        return doc,file

    def data(self,doc):
        targets=[dict(doctype=doc.doctype,name=doc.name,modified=str(doc.modified))]
        q=api.preview(self.prop.name,dict(targets=targets),"retire_sensitive")
        return dict(targets=targets,reason="Aplicación de política sintética revisada",acceptance=q["acceptance"],confirm=True)

    def retire(self,doc,key=None):
        return api.execute(self.prop.name,"retire_sensitive",key or uuid.uuid4().hex,self.data(doc))

    def test_identity_versions_and_file_metadata_commit_before_bytes_are_removed(self):
        guest,file=self.guest()
        number=guest.identity_number
        path=Path(file.get_full_path())
        ledger_counts={dt:frappe.db.count(dt) for dt in ("GL Entry","Payment Ledger Entry","Stock Ledger Entry")}
        catalog=api.retention_candidates(self.prop.name)
        self.assertIn(guest.name,[r["name"] for r in catalog["targets"]])
        values=self.data(guest)
        key=uuid.uuid4().hex
        result=api.execute(self.prop.name,"retire_sensitive",key,values)
        self.assertEqual(api.execute(self.prop.name,"retire_sensitive",key,values),result)
        self.assertEqual(result["status"],"Pending")
        guest.reload()
        self.assertFalse(guest.identity_number or guest.identity_type or guest.identity_file)
        self.assertFalse(frappe.db.exists("File",file.name))
        self.assertTrue(path.exists())
        versions=frappe.get_all("Version",filters={"ref_doctype":guest.doctype,"docname":guest.name},pluck="data")
        self.assertFalse(any(number in data for data in versions))
        self.assertFalse(any(file.file_url in data for data in versions))
        self.assertEqual(privacy.purge_run(result["run"])["status"],"Completed")
        self.assertFalse(path.exists())
        run=frappe.get_doc("HS Retention Run",result["run"])
        self.assertEqual(run.files[0].status,"Deleted")
        self.assertFalse(run.files[0].file_url or run.files[0].content_hash)
        self.assertEqual(privacy.purge_run(run.name)["attempts"],1)
        self.assertEqual(ledger_counts,{dt:frappe.db.count(dt) for dt in ledger_counts})

    def test_recent_upload_and_future_booking_prevent_retirement(self):
        guest,file=self.guest()
        values=self.data(guest)
        fresh=save_file("evidencia-reciente-"+uuid.uuid4().hex+".txt",uuid.uuid4().hex.encode(),guest.doctype,guest.name,is_private=1)
        with self.assertRaises(frappe.ValidationError):
            api.execute(self.prop.name,"retire_sensitive",uuid.uuid4().hex,values)
        self.assertTrue(frappe.db.exists("File",file.name))
        self.age(fresh,creation=self.old)
        room=frappe.get_doc("HS Room",{"property":self.prop.name})
        start=now_datetime()+timedelta(days=60)
        booking=dict(guest=guest.name,customer=guest.customer,starts_at=str(start),ends_at=str(start+timedelta(days=1)),rooms=[dict(category=room.category,room=room.name,people=1)])
        booking["acceptance"]=api.preview(self.prop.name,booking)["acceptance"]
        api.execute(self.prop.name,"reserve",uuid.uuid4().hex,booking)
        self.assertNotIn(guest.name,[r["name"] for r in api.retention_candidates(self.prop.name)["targets"]])
        with self.assertRaises(frappe.ValidationError):
            self.retire(guest)

    def test_cross_scope_approval_and_active_companion_are_rejected(self):
        guest,file=self.guest()
        values=self.data(guest)
        frappe.set_user("supervisor@hospitality.example.invalid")
        with self.assertRaises(frappe.PermissionError):
            api.retention_candidates(self.prop.name)
        with self.assertRaises(frappe.PermissionError):
            api.execute(self.prop.name,"retire_sensitive",uuid.uuid4().hex,values)
        frappe.set_user("Administrator")
        other=frappe.get_doc("HS Property",{"property_name":"Motel Luna Demo"})
        with self.assertRaises(frappe.PermissionError):
            api.preview(other.name,values,"retire_sensitive")
        main=frappe.get_doc("HS Guest",{"property":self.prop.name,"name":["!=",guest.name]})
        room=frappe.get_doc("HS Room",{"property":self.prop.name})
        start=now_datetime()
        visit=dict(guest=main.name,customer=main.customer,starts_at=str(start),ends_at=str(start+timedelta(days=1)),rooms=[dict(category=room.category,room=room.name,people=2)])
        visit["acceptance"]=api.preview(self.prop.name,visit)["acceptance"]
        stay=api.execute(self.prop.name,"walk_in",uuid.uuid4().hex,visit)
        doc=frappe.get_doc("HS Stay",stay["stay"])
        api.execute(self.prop.name,"companions",uuid.uuid4().hex,dict(stay=doc.name,modified=str(doc.modified),guests=[guest.name]))
        with self.assertRaises(frappe.ValidationError):
            self.retire(guest)

    def test_rollback_after_redaction_restores_database_without_deleting_bytes(self):
        guest,file=self.guest()
        number=guest.identity_number
        path=Path(file.get_full_path())
        original=privacy.audit
        def fail(prop,action,*args,**kwargs):
            if action=="Approve data retention":
                raise RuntimeError("Fallo sintético después de retirar metadatos")
            return original(prop,action,*args,**kwargs)
        with patch("hospitality_suite.privacy.audit",side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.retire(guest)
        guest.reload()
        self.assertEqual(guest.identity_number,number)
        self.assertTrue(frappe.db.exists("File",file.name))
        self.assertTrue(path.exists())
        self.assertEqual(frappe.db.count("HS Retention Run"),0)
        self.assertEqual(privacy.purge_run("ejecucion-inexistente"),dict(status="Missing"))
        result=self.retire(guest)
        self.assertEqual(privacy.purge_run(result["run"])["status"],"Completed")

    def test_shared_content_is_preserved_for_the_other_document(self):
        guest,file=self.guest()
        other,_=self.guest(with_file=False)
        path=Path(file.get_full_path())
        shared=save_file("copia-sintetica.txt",path.read_bytes(),other.doctype,other.name,is_private=1)
        self.assertEqual(shared.content_hash,file.content_hash)
        result=self.retire(guest)
        privacy.purge_run(result["run"])
        self.assertTrue(path.exists())
        self.assertTrue(frappe.db.exists("File",shared.name))
        self.assertEqual(frappe.get_doc("HS Retention Run",result["run"]).files[0].status,"Shared")

    def test_file_failure_has_bounded_attempts_and_authorized_recovery(self):
        guest,file=self.guest()
        path=Path(file.get_full_path())
        result=self.retire(guest)
        with patch("frappe.core.doctype.file.file.File.delete_file_data_content",side_effect=PermissionError("Archivo sintético bloqueado")):
            for attempt in range(1,4):
                outcome=privacy.purge_run(result["run"])
                self.assertEqual(outcome["attempts"],attempt)
                self.assertEqual(outcome["status"],"Failed")
            self.assertEqual(privacy.purge_run(result["run"])["attempts"],3)
        self.assertTrue(path.exists())
        run=frappe.get_doc("HS Retention Run",result["run"])
        frappe.set_user("manager@hospitality.example.invalid")
        api.execute(self.prop.name,"retry_retention",uuid.uuid4().hex,dict(run=run.name,modified=str(run.modified),reason="Se retiró el bloqueo sintético"))
        frappe.set_user("Administrator")
        self.assertEqual(privacy.purge_run(run.name)["status"],"Completed")
        self.assertFalse(path.exists())

    def test_manager_approval_queues_only_disposal_as_system_and_restores_user(self):
        guest,file=self.guest()
        frappe.set_user("manager@hospitality.example.invalid")
        result=self.retire(guest)
        self.assertEqual(frappe.db.get_value("HS Retention Run",result["run"],"approved_by"),frappe.session.user)
        self.queue_patch.stop()
        run=frappe.get_doc("HS Retention Run",result["run"])
        captured=[]
        with patch("frappe.enqueue",side_effect=lambda *a,**kw:captured.append((frappe.session.user,a,kw))):
            privacy.queue(run)
        self.assertEqual(frappe.session.user,"manager@hospitality.example.invalid")
        self.assertEqual(captured[0][0],"Administrator")
        self.assertEqual(captured[0][1],("hospitality_suite.privacy.purge_run",))
        self.assertTrue(captured[0][2]["enqueue_after_commit"])
        self.assertEqual(captured[0][2]["run_name"],run.name)
        with self.assertRaises(frappe.PermissionError):
            privacy.purge_run(run.name)
        frappe.set_user("Administrator")
        self.assertEqual(privacy.purge_run(run.name)["status"],"Completed")

    def test_closed_operational_evidence_requires_completion_and_keeps_history(self):
        room=frappe.get_doc("HS Room",{"property":self.prop.name})
        incident=api.execute(self.prop.name,"incident",uuid.uuid4().hex,dict(room=room.name,kind="Lost Property",description="Objeto sintético sin datos personales"))["incident"]
        order=api.execute(self.prop.name,"maintenance",uuid.uuid4().hex,dict(room=room.name,blocks_room=False,title="Revisión sintética",starts_at=str(now_datetime()),ends_at=str(now_datetime()+timedelta(hours=1))))["order"]
        for dt,name,action in (("HS Incident",incident,"incident"),("HS Maintenance Order",order,"maintenance")):
            doc=frappe.get_doc(dt,name)
            file=save_file("evidencia-"+uuid.uuid4().hex+".txt",uuid.uuid4().hex.encode(),dt,name,is_private=1)
            values={"incident" if action=="incident" else "order":name,"modified":str(doc.modified),"evidence":file.file_url}
            api.execute(self.prop.name,action,uuid.uuid4().hex,values)
            doc.reload()
            for attached in privacy.files_for(doc):
                self.age(frappe.get_doc("File",attached.name),creation=self.old)
            self.age(doc)
            with self.assertRaises(frappe.ValidationError):
                self.data(doc)
            values={"incident" if action=="incident" else "order":name,"modified":str(doc.modified)}
            values.update(dict(resolve=True,resolution="Entrega ficticia verificada") if action=="incident" else dict(status="Completed",notes="Revisión ficticia terminada"))
            api.execute(self.prop.name,action,uuid.uuid4().hex,values)
            doc.reload()
            self.age(doc)
            result=self.retire(doc)
            self.assertEqual(privacy.purge_run(result["run"])["status"],"Completed")
            doc.reload()
            self.assertFalse(doc.evidence)
            self.assertEqual(doc.status,"Resolved" if action=="incident" else "Completed")
            self.assertTrue(doc.resolution if action=="incident" else doc.notes)

    def test_candidate_labels_identify_closed_incidents_without_exposing_their_description(self):
        rooms=frappe.get_all('HS Room',filters={'property':self.prop.name},fields=['name','room_number'],order_by='room_number',limit=2)
        selected=[]
        for room in rooms:
            name=api.execute(self.prop.name,'incident',uuid.uuid4().hex,dict(room=room.name,kind='Lost Property',
                description='Detalle de custodia que no debe copiarse al selector'))['incident']
            doc=frappe.get_doc('HS Incident',name)
            file=save_file('etiqueta-'+uuid.uuid4().hex+'.txt',uuid.uuid4().hex.encode(),doc.doctype,doc.name,is_private=1)
            api.execute(self.prop.name,'incident',uuid.uuid4().hex,dict(incident=doc.name,modified=str(doc.modified),evidence=file.file_url))
            doc.reload()
            api.execute(self.prop.name,'incident',uuid.uuid4().hex,dict(incident=doc.name,modified=str(doc.modified),resolve=True,resolution='Entrega sintética'))
            doc.reload();self.age(doc)
            for attached in privacy.files_for(doc):self.age(frappe.get_doc('File',attached.name),creation=self.old)
            selected.append((doc.name,room.room_number))
        frappe.set_user('manager@hospitality.example.invalid')
        targets={row['name']:row for row in api.retention_candidates(self.prop.name)['targets']}
        labels=[targets[name]['label'] for name,_ in selected]
        self.assertEqual(len(set(labels)),2)
        for name,room in selected:
            self.assertIn(name,targets[name]['label']);self.assertIn(room,targets[name]['label'])
            self.assertNotIn('Detalle de custodia',targets[name]['label'])
