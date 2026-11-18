with open('cars/models.py') as f:
    c = f.read()
c += '\n\ndef testimonial_photo_upload_to(instance, filename):\n    return f"testimonials/{instance.testimonial_id or \\"tmp\\"}/{filename}"\n\n\nclass TestimonialPhoto(models.Model):\n    testimonial = models.ForeignKey(Testimonial, on_delete=models.CASCADE, related_name="photos")\n    photo = models.ImageField(upload_to=testimonial_photo_upload_to)\n    uploaded_at = models.DateTimeField(auto_now_add=True)\n\n    def __str__(self):\n        return f"Photo for {self.testimonial}"\n'
with open('cars/models.py','w') as f:
    f.write(c)
print('done')
